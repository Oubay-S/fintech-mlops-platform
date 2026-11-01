"""Model Registry Governance, Promotion & Instant Rollback CLI (Role 5).

Usage:
    # Promote validated @candidate to @staging
    python -m ml.pipeline.promote_model --from-alias candidate --to-alias staging

    # Promote @staging to @production (rotates previous @production -> @previous)
    python -m ml.pipeline.promote_model --from-alias staging --to-alias production [--dry-run]

    # Instant rollback from @previous to @production
    python -m ml.pipeline.promote_model --from-alias previous --to-alias production

Governance Rules:
    1. A model MUST pass `validate_gate` before promotion.
    2. Promoting a run tagged `data_source=synthetic` to `@production` is strictly forbidden (exit 1).
    3. When promoting V_new to `@production`, any distinct active `@production` version V_old
       is atomically assigned the `@previous` alias.
    4. Promoting a version that already holds the target alias is a safe idempotent no-op (exit 0).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from typing import Any

from .mlflow_config import (
    CANDIDATE_ALIAS,
    DATA_SOURCE_TAG,
    EXIT_GATE_FAILURE,
    EXIT_INFRA_ERROR,
    EXIT_SUCCESS,
    MODEL_ARTIFACT_PATH,
    PREVIOUS_ALIAS,
    PRODUCTION_ALIAS,
    STAGING_ALIAS,
    GateThresholds,
    PipelineGateError,
    PipelineInfraError,
    load_gate_thresholds,
    resolve_target_run,
    resolve_tracking_uri,
)
from .validate_gate import evaluate_run_against_gate

ALLOWED_TARGET_ALIASES = {
    CANDIDATE_ALIAS,
    STAGING_ALIAS,
    PRODUCTION_ALIAS,
    PREVIOUS_ALIAS,
}


@dataclass(frozen=True)
class PromotionReport:
    """Structured output of a model promotion or dry-run operation."""

    promoted: bool
    dry_run: bool
    idempotent_noop: bool
    exit_code: int
    model_name: str
    promoted_version: str
    run_id: str
    from_alias: str | None
    to_alias: str
    previous_production_version: str | None
    data_source: str | None
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _get_current_alias_version(client: Any, model_name: str, alias: str) -> str | None:
    """Return the version string currently holding `alias`, or `None` if unassigned."""
    try:
        mv = client.get_model_version_by_alias(name=model_name, alias=alias)
        return str(mv.version)
    except Exception:  # noqa: BLE001
        return None


def _ensure_registered_version(
    client: Any,
    *,
    model_name: str,
    run_id: str,
    existing_version: str | None,
    dry_run: bool,
) -> str:
    """Return existing registered version for `run_id` or register it if missing."""
    if existing_version is not None:
        return existing_version

    if dry_run:
        return "dry-run-unregistered"

    import mlflow

    model_uri = f"runs:/{run_id}/{MODEL_ARTIFACT_PATH}"
    mv = mlflow.register_model(model_uri=model_uri, name=model_name)
    return str(mv.version)


def promote_model(
    *,
    tracking_uri: str,
    to_alias: str,
    from_alias: str | None = None,
    run_id: str | None = None,
    model_name: str | None = None,
    dry_run: bool = False,
    thresholds: GateThresholds | None = None,
) -> PromotionReport:
    """Validate and promote a model version in the MLflow Model Registry."""
    cfg = thresholds or load_gate_thresholds()
    target_alias = to_alias.strip().lower()
    if target_alias not in ALLOWED_TARGET_ALIASES:
        raise PipelineInfraError(
            f"Unsupported target alias '{to_alias}'. Allowed: {sorted(ALLOWED_TARGET_ALIASES)}"
        )

    resolved_model_name = model_name or cfg.model_name
    target = resolve_target_run(
        tracking_uri=tracking_uri,
        model_name=resolved_model_name,
        alias=from_alias,
        run_id=run_id,
    )

    tags = {str(k): str(v) for k, v in target.run.data.tags.items()}
    data_source = tags.get(DATA_SOURCE_TAG, "").strip().lower()

    # 1. Governance block: NEVER allow synthetic data_source in @production
    if target_alias == PRODUCTION_ALIAS:
        if not data_source:
            raise PipelineGateError(
                f"Cannot promote run '{target.run_id}' to @{PRODUCTION_ALIAS}: "
                f"missing '{DATA_SOURCE_TAG}' tag."
            )
        if data_source in cfg.forbidden_production_data_sources:
            raise PipelineGateError(
                f"Governance policy violation: run '{target.run_id}' has "
                f"{DATA_SOURCE_TAG}='{data_source}', which is strictly forbidden in @{PRODUCTION_ALIAS}."
            )

    # 2. Enforce Quality Gate before promotion
    gate_report = evaluate_run_against_gate(
        tracking_uri=tracking_uri,
        model_name=resolved_model_name,
        alias=from_alias,
        run_id=target.run_id if not from_alias else None,
        thresholds=cfg,
    )
    if not gate_report.passed:
        joined = "; ".join(gate_report.failures)
        raise PipelineGateError(
            f"Cannot promote run '{target.run_id}' to @{target_alias} because Quality Gate failed: {joined}"
        )

    try:
        from mlflow.tracking import MlflowClient

        client = MlflowClient(tracking_uri=tracking_uri)
        version_str = _ensure_registered_version(
            client,
            model_name=resolved_model_name,
            run_id=target.run_id,
            existing_version=target.model_version,
            dry_run=dry_run,
        )

        current_target_holder = _get_current_alias_version(
            client, resolved_model_name, target_alias
        )
        previous_prod_version: str | None = None

        # 3. Idempotence check
        if current_target_holder == version_str:
            if target_alias == PRODUCTION_ALIAS:
                previous_prod_version = _get_current_alias_version(
                    client, resolved_model_name, PREVIOUS_ALIAS
                )
            return PromotionReport(
                promoted=True,
                dry_run=dry_run,
                idempotent_noop=True,
                exit_code=EXIT_SUCCESS,
                model_name=resolved_model_name,
                promoted_version=version_str,
                run_id=target.run_id,
                from_alias=from_alias,
                to_alias=target_alias,
                previous_production_version=previous_prod_version,
                data_source=data_source or None,
                message=(
                    f"Version {version_str} already holds alias @{target_alias}; "
                    "idempotent no-op."
                ),
            )

        # 4. Atomic @previous rotation when promoting to @production
        if target_alias == PRODUCTION_ALIAS and current_target_holder is not None:
            previous_prod_version = current_target_holder
            if not dry_run:
                client.set_registered_model_alias(
                    name=resolved_model_name,
                    alias=PREVIOUS_ALIAS,
                    version=previous_prod_version,
                )

        if not dry_run:
            client.set_registered_model_alias(
                name=resolved_model_name,
                alias=target_alias,
                version=version_str,
            )

        action_word = "Would promote" if dry_run else "Promoted"
        msg = f"{action_word} {resolved_model_name} version {version_str} to @{target_alias}."
        if previous_prod_version:
            msg += f" Rotated version {previous_prod_version} to @{PREVIOUS_ALIAS}."

        return PromotionReport(
            promoted=True,
            dry_run=dry_run,
            idempotent_noop=False,
            exit_code=EXIT_SUCCESS,
            model_name=resolved_model_name,
            promoted_version=version_str,
            run_id=target.run_id,
            from_alias=from_alias,
            to_alias=target_alias,
            previous_production_version=previous_prod_version,
            data_source=data_source or None,
            message=msg,
        )
    except (PipelineGateError, PipelineInfraError):
        raise
    except Exception as exc:
        raise PipelineInfraError(
            f"MLflow Registry promotion failed for '{resolved_model_name}': {exc}"
        ) from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--from-alias",
        default=None,
        help="Source alias to promote from (e.g. candidate, staging, previous)",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Source MLflow run_id to promote (if --from-alias is not used)",
    )
    parser.add_argument(
        "--to-alias",
        default=STAGING_ALIAS,
        help="Target alias to assign (staging or production)",
    )
    parser.add_argument(
        "--model-name",
        default=None,
        help="Registered model name override",
    )
    parser.add_argument(
        "--tracking-uri",
        default=None,
        help="MLflow tracking URI override",
    )
    parser.add_argument(
        "--thresholds",
        default=None,
        help="Path to gate_thresholds.yaml",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and simulate alias transitions without modifying MLflow Registry",
    )
    args = parser.parse_args(argv)

    try:
        thresholds = load_gate_thresholds(args.thresholds)
        tracking_uri = resolve_tracking_uri(args.tracking_uri)
        source_alias = (
            args.from_alias if (args.from_alias or args.run_id) else CANDIDATE_ALIAS
        )
        report = promote_model(
            tracking_uri=tracking_uri,
            to_alias=args.to_alias,
            from_alias=source_alias,
            run_id=args.run_id,
            model_name=args.model_name,
            dry_run=args.dry_run,
            thresholds=thresholds,
        )
        print(json.dumps(report.to_dict(), indent=2))
        return report.exit_code
    except PipelineGateError as exc:
        print(
            json.dumps(
                {
                    "promoted": False,
                    "exit_code": EXIT_GATE_FAILURE,
                    "error": str(exc),
                },
                indent=2,
            ),
            file=sys.stderr,
        )
        return EXIT_GATE_FAILURE
    except PipelineInfraError as exc:
        print(
            json.dumps(
                {
                    "promoted": False,
                    "exit_code": EXIT_INFRA_ERROR,
                    "error": str(exc),
                },
                indent=2,
            ),
            file=sys.stderr,
        )
        return EXIT_INFRA_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
