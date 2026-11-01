"""Read-only Conformal Prediction verification module (MLOps — Role 5).

IMPORTANT BOUNDARY:
- Conformal calibration (`q_hat_fraud`, `q_hat_legit`) belongs strictly to the Data Scientist (Role 4).
- This module NEVER recalibrates or alters conformal thresholds.
- It verifies:
  1. Schema validity and SHA-256 cryptographic coupling of `uncertainty_config.json`.
  2. Empirical coverage on the test split (`coverage_legit` and `coverage_fraud` >= `1 - alpha - tolerance`).
  3. Operational human-review budget (`expected_review_rate <= max_expected_review_rate`, i.e. <= 5%).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

from ml.common.artifact_contract import (
    UNCERTAINTY_CONFIG_ARTIFACT,
    UNCERTAINTY_SHA256_TAG,
    UncertaintyConfigContract,
    verify_uncertainty_sha256,
)

from .mlflow_config import (
    CANDIDATE_ALIAS,
    EXIT_GATE_FAILURE,
    EXIT_INFRA_ERROR,
    EXIT_SUCCESS,
    GateThresholds,
    PipelineInfraError,
    download_json_artifact,
    load_gate_thresholds,
    resolve_target_run,
    resolve_tracking_uri,
)


@dataclass(frozen=True)
class ConformalEvalResult:
    """Result of read-only conformal verification for a candidate MLflow run."""

    passed: bool
    run_id: str
    method: str
    confidence_level: float
    min_required_coverage: float
    q_hat_fraud: float
    q_hat_legit: float
    coverage_legit: float | None
    coverage_fraud: float | None
    expected_review_rate: float
    max_expected_review_rate: float
    sha256_verified: bool
    failures: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_existing_thresholds_on_split(
    *,
    p_fraud: np.ndarray,
    y_true: np.ndarray,
    config: UncertaintyConfigContract,
) -> dict[str, float]:
    """Evaluate pre-calibrated `config` thresholds on `(p_fraud, y_true)` without recalibrating."""
    probs = np.asarray(p_fraud, dtype=float)
    labels = np.asarray(y_true, dtype=int)
    if len(probs) == 0 or len(probs) != len(labels):
        raise ValueError(
            "p_fraud and y_true must be non-empty arrays of identical length."
        )

    include_legit = probs <= config.q_hat_legit
    include_fraud = (1.0 - probs) <= config.q_hat_fraud
    set_sizes = include_legit.astype(int) + include_fraud.astype(int)

    legit_mask = labels == 0
    fraud_mask = labels == 1

    cov_legit = float(np.mean(include_legit[legit_mask])) if np.any(legit_mask) else 1.0
    cov_fraud = float(np.mean(include_fraud[fraud_mask])) if np.any(fraud_mask) else 1.0
    model_uncertain_rate = float(np.mean(set_sizes != 1))

    return {
        "coverage_legit": cov_legit,
        "coverage_fraud": cov_fraud,
        "model_uncertain_rate": model_uncertain_rate,
        "expected_review_rate": model_uncertain_rate,
        "avg_set_size": float(np.mean(set_sizes)),
    }


def verify_conformal_artifact_and_coverage(
    *,
    run_id: str,
    run_tags: dict[str, str],
    run_metrics: dict[str, float],
    raw_config: dict[str, Any],
    raw_bytes: bytes,
    thresholds: GateThresholds,
) -> ConformalEvalResult:
    """Validate `uncertainty_config.json` integrity, SHA-256 coupling, coverage, and review budget."""
    try:
        config = UncertaintyConfigContract.from_dict(raw_config)
    except Exception as exc:
        raise PipelineInfraError(
            f"Malformed uncertainty_config.json in run '{run_id}': {exc}"
        ) from exc

    failures: list[str] = []

    # 1. Verify atomic SHA-256 coupling with the run tag
    expected_sha256 = run_tags.get(UNCERTAINTY_SHA256_TAG, "").strip()
    sha256_ok = False
    if not expected_sha256:
        failures.append(
            f"Missing required atomic tag '{UNCERTAINTY_SHA256_TAG}' on MLflow run '{run_id}'."
        )
    else:
        sha256_ok = verify_uncertainty_sha256(
            expected_sha256=expected_sha256,
            config=config,
            raw_bytes=raw_bytes,
            raw_dict=raw_config,
        )
        if not sha256_ok:
            failures.append(
                f"SHA-256 mismatch for '{UNCERTAINTY_CONFIG_ARTIFACT}': tag {expected_sha256} "
                f"does not match artifact digest {config.sha256()}."
            )

    # 2. Extract empirical coverage and review rate from run metrics or config.metrics_summary
    summary = config.metrics_summary
    cov_legit = run_metrics.get("coverage_legit", summary.get("coverage_legit"))
    cov_fraud = run_metrics.get("coverage_fraud", summary.get("coverage_fraud"))

    review_rate = run_metrics.get(
        "expected_review_rate",
        run_metrics.get(
            "human_review_rate_transfer_cashout",
            summary.get("expected_review_rate"),
        ),
    )

    min_required_cov = float(
        config.confidence_level - thresholds.finite_sample_tolerance
    )

    if thresholds.require_empirical_coverage:
        if cov_legit is None:
            failures.append(
                "Missing empirical 'coverage_legit' in MLflow metrics and uncertainty_config.json."
            )
        elif float(cov_legit) < min_required_cov:
            failures.append(
                f"Empirical coverage_legit ({float(cov_legit):.4f}) is below required target "
                f"({min_required_cov:.4f} for confidence_level={config.confidence_level})."
            )

        if cov_fraud is None:
            failures.append(
                "Missing empirical 'coverage_fraud' in MLflow metrics and uncertainty_config.json."
            )
        elif float(cov_fraud) < min_required_cov:
            failures.append(
                f"Empirical coverage_fraud ({float(cov_fraud):.4f}) is below required target "
                f"({min_required_cov:.4f} for confidence_level={config.confidence_level})."
            )

    if review_rate is None:
        failures.append(
            "Missing 'expected_review_rate' in MLflow metrics and uncertainty_config.json."
        )
        resolved_review = -1.0
    else:
        resolved_review = float(review_rate)
        if resolved_review > thresholds.max_expected_review_rate:
            failures.append(
                f"Operational review rate ({resolved_review:.4f}) exceeds maximum budget "
                f"({thresholds.max_expected_review_rate:.4f})."
            )

    return ConformalEvalResult(
        passed=len(failures) == 0,
        run_id=run_id,
        method=config.method,
        confidence_level=config.confidence_level,
        min_required_coverage=min_required_cov,
        q_hat_fraud=config.q_hat_fraud,
        q_hat_legit=config.q_hat_legit,
        coverage_legit=float(cov_legit) if cov_legit is not None else None,
        coverage_fraud=float(cov_fraud) if cov_fraud is not None else None,
        expected_review_rate=resolved_review,
        max_expected_review_rate=thresholds.max_expected_review_rate,
        sha256_verified=sha256_ok,
        failures=failures,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--alias", default=None, help="Model Registry alias (e.g. candidate)"
    )
    parser.add_argument("--run-id", default=None, help="Explicit MLflow run_id")
    parser.add_argument(
        "--model-name", default=None, help="Registered model name override"
    )
    parser.add_argument(
        "--tracking-uri", default=None, help="MLflow tracking URI override"
    )
    parser.add_argument(
        "--thresholds", default=None, help="Path to gate_thresholds.yaml"
    )
    args = parser.parse_args(argv)

    try:
        thresholds = load_gate_thresholds(args.thresholds)
        tracking_uri = resolve_tracking_uri(args.tracking_uri)
        alias = args.alias if (args.alias or args.run_id) else CANDIDATE_ALIAS
        target = resolve_target_run(
            tracking_uri=tracking_uri,
            model_name=args.model_name or thresholds.model_name,
            alias=alias,
            run_id=args.run_id,
        )
        raw_config, raw_bytes = download_json_artifact(
            tracking_uri=tracking_uri,
            run_id=target.run_id,
            artifact_path=UNCERTAINTY_CONFIG_ARTIFACT,
        )
        result = verify_conformal_artifact_and_coverage(
            run_id=target.run_id,
            run_tags=dict(target.run.data.tags),
            run_metrics={k: float(v) for k, v in target.run.data.metrics.items()},
            raw_config=raw_config,
            raw_bytes=raw_bytes,
            thresholds=thresholds,
        )
        print(json.dumps(result.to_dict(), indent=2))
        return EXIT_SUCCESS if result.passed else EXIT_GATE_FAILURE
    except PipelineInfraError as exc:
        print(json.dumps({"status": "INFRA_ERROR", "error": str(exc)}), file=sys.stderr)
        return EXIT_INFRA_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
