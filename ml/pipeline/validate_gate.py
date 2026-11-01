"""Automated MLOps Quality Gate inspecting an MLflow run without retraining (Role 5).

Usage:
    python -m ml.pipeline.validate_gate --alias candidate
    python -m ml.pipeline.validate_gate --run-id <RUN_ID>

Exit Codes:
    0 (EXIT_SUCCESS): All scalar, conformal, latency, and statistical checks passed.
    1 (EXIT_GATE_FAILURE): One or more business / statistical / conformal thresholds failed.
    2 (EXIT_INFRA_ERROR): MLflow unreachable, missing run/alias, or missing required JSON artifact.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from typing import Any

from ml.common.artifact_contract import UNCERTAINTY_CONFIG_ARTIFACT

from .conformal_eval import ConformalEvalResult, verify_conformal_artifact_and_coverage
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
class GateValidationReport:
    """Structured report emitted by `validate_gate.py`."""

    passed: bool
    exit_code: int
    model_name: str
    model_version: str | None
    alias: str | None
    run_id: str
    data_source: str | None
    metrics_checked: dict[str, float]
    conformal_evaluation: dict[str, Any]
    statistical_validation: dict[str, Any]
    failures: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_statistical_artifact(
    stat_payload: dict[str, Any],
    thresholds: GateThresholds,
) -> tuple[bool, list[str], dict[str, Any]]:
    """Validate `statistical_validation.json` for Friedman p < 0.05 and Wilcoxon/Holm superiority.

    Supports both:
    - Top-level summary schema: `{"friedman_p": 0.0001, "wilcoxon_holm_significant": true, "min_holm_p": 0.0006}`
    - Role 4 `run_statistics.py` findings list schema: `{"findings": [{"friedman_p": ..., "pairs": [{"holm_p": ...}]}]}`
    """
    failures: list[str] = []

    friedman_p: float | None = None
    min_holm_p: float | None = None
    holm_significant: bool = False

    if "friedman_p" in stat_payload and isinstance(
        stat_payload["friedman_p"], (int, float)
    ):
        friedman_p = float(stat_payload["friedman_p"])
    if "min_holm_p" in stat_payload and isinstance(
        stat_payload["min_holm_p"], (int, float)
    ):
        min_holm_p = float(stat_payload["min_holm_p"])
    if "wilcoxon_holm_significant" in stat_payload:
        holm_significant = bool(stat_payload["wilcoxon_holm_significant"])

    findings = stat_payload.get("findings")
    if isinstance(findings, list) and len(findings) > 0:
        f_pvals: list[float] = []
        h_pvals: list[float] = []
        for item in findings:
            if isinstance(item, dict) and isinstance(
                item.get("friedman_p"), (int, float)
            ):
                f_pvals.append(float(item["friedman_p"]))
                for pair in item.get("pairs", []):
                    if isinstance(pair, dict) and isinstance(
                        pair.get("holm_p"), (int, float)
                    ):
                        h_pvals.append(float(pair["holm_p"]))
        if f_pvals and friedman_p is None:
            friedman_p = min(f_pvals)
        if h_pvals and min_holm_p is None:
            min_holm_p = min(h_pvals)

    if min_holm_p is not None and min_holm_p < thresholds.max_wilcoxon_holm_p_value:
        holm_significant = True

    if friedman_p is None:
        raise PipelineInfraError(
            f"'{thresholds.statistical_artifact_name}' does not contain 'friedman_p' or 'findings'."
        )

    if friedman_p >= thresholds.max_friedman_p_value:
        failures.append(
            f"Statistical test failed: Friedman p-value ({friedman_p:.6g}) >= "
            f"threshold ({thresholds.max_friedman_p_value}). Null hypothesis not rejected."
        )

    if thresholds.require_wilcoxon_holm_superiority and not holm_significant:
        failures.append(
            "Statistical test failed: Pairwise Wilcoxon signed-rank test with Holm correction "
            f"did not confirm significant superiority (min_holm_p={min_holm_p})."
        )

    summary = {
        "friedman_p": friedman_p,
        "min_holm_p": min_holm_p,
        "wilcoxon_holm_significant": holm_significant,
        "passed": len(failures) == 0,
    }
    return len(failures) == 0, failures, summary


def evaluate_run_against_gate(
    *,
    tracking_uri: str,
    model_name: str | None = None,
    alias: str | None = None,
    run_id: str | None = None,
    thresholds: GateThresholds | None = None,
) -> GateValidationReport:
    """Inspect an MLflow run directly and validate all MLOps Quality Gate criteria."""
    cfg = thresholds or load_gate_thresholds()
    target = resolve_target_run(
        tracking_uri=tracking_uri,
        model_name=model_name or cfg.model_name,
        alias=alias,
        run_id=run_id,
    )

    tags = {str(k): str(v) for k, v in target.run.data.tags.items()}
    metrics = {str(k): float(v) for k, v in target.run.data.metrics.items()}
    failures: list[str] = []

    # 1. Required tags check
    for req_tag in cfg.required_run_tags:
        if not tags.get(req_tag, "").strip():
            failures.append(f"Missing required MLflow run tag: '{req_tag}'.")

    # 2. Download & verify uncertainty_config.json + conformal coverage & review budget
    raw_uncertainty, raw_uncertainty_bytes = download_json_artifact(
        tracking_uri=tracking_uri,
        run_id=target.run_id,
        artifact_path=UNCERTAINTY_CONFIG_ARTIFACT,
    )
    conformal_res: ConformalEvalResult = verify_conformal_artifact_and_coverage(
        run_id=target.run_id,
        run_tags=tags,
        run_metrics=metrics,
        raw_config=raw_uncertainty,
        raw_bytes=raw_uncertainty_bytes,
        thresholds=cfg,
    )
    failures.extend(conformal_res.failures)

    # Merge metrics from uncertainty_config.metrics_summary as fallback if not top-level
    summary_metrics = raw_uncertainty.get("metrics_summary", {})
    if isinstance(summary_metrics, dict):
        for k, v in summary_metrics.items():
            if (
                k not in metrics
                and isinstance(v, (int, float))
                and not isinstance(v, bool)
            ):
                metrics[str(k)] = float(v)

    # 3. Scalar performance & latency budget checks
    min_checks = (
        ("pr_auc", cfg.min_pr_auc),
        ("roc_auc", cfg.min_roc_auc),
        ("f1", cfg.min_f1),
        ("recall", cfg.min_recall),
    )
    for metric_name, min_val in min_checks:
        val = metrics.get(metric_name)
        if val is None:
            failures.append(
                f"Missing required metric '{metric_name}' on run '{target.run_id}'."
            )
        elif val < min_val:
            failures.append(
                f"Metric '{metric_name}' ({val:.4f}) is below minimum threshold ({min_val:.4f})."
            )

    brier = metrics.get("brier_score")
    if brier is None:
        failures.append(
            f"Missing required metric 'brier_score' on run '{target.run_id}'."
        )
    elif brier > cfg.max_brier_score:
        failures.append(
            f"Metric 'brier_score' ({brier:.6f}) exceeds maximum threshold ({cfg.max_brier_score:.6f})."
        )

    p95_ms = metrics.get("inference_p95_ms")
    if p95_ms is None:
        failures.append(
            f"Missing required metric 'inference_p95_ms' on run '{target.run_id}'."
        )
    elif p95_ms >= cfg.max_inference_p95_ms:
        failures.append(
            f"Latency 'inference_p95_ms' ({p95_ms:.2f} ms) violates budget (< {cfg.max_inference_p95_ms:.1f} ms)."
        )

    # 4. Statistical validation artifact check (Friedman + Wilcoxon/Holm)
    stat_summary: dict[str, Any] = {"required": cfg.statistical_validation_required}
    if cfg.statistical_validation_required:
        raw_stat, _ = download_json_artifact(
            tracking_uri=tracking_uri,
            run_id=target.run_id,
            artifact_path=cfg.statistical_artifact_name,
        )
        _, stat_failures, stat_summary = validate_statistical_artifact(raw_stat, cfg)
        failures.extend(stat_failures)

    passed = len(failures) == 0
    return GateValidationReport(
        passed=passed,
        exit_code=EXIT_SUCCESS if passed else EXIT_GATE_FAILURE,
        model_name=target.model_name,
        model_version=target.model_version,
        alias=target.alias,
        run_id=target.run_id,
        data_source=tags.get("data_source"),
        metrics_checked={
            k: round(float(metrics[k]), 6)
            for k in (
                "pr_auc",
                "roc_auc",
                "f1",
                "recall",
                "brier_score",
                "expected_review_rate",
                "inference_p95_ms",
            )
            if k in metrics
        },
        conformal_evaluation=conformal_res.to_dict(),
        statistical_validation=stat_summary,
        failures=failures,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--alias",
        default=None,
        help="Model Registry alias to inspect (defaults to 'candidate' if --run-id is not given)",
    )
    parser.add_argument(
        "--run-id", default=None, help="Explicit MLflow run_id to inspect"
    )
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
        report = evaluate_run_against_gate(
            tracking_uri=tracking_uri,
            model_name=args.model_name,
            alias=alias,
            run_id=args.run_id,
            thresholds=thresholds,
        )
        print(json.dumps(report.to_dict(), indent=2))
        return report.exit_code
    except PipelineInfraError as exc:
        print(
            json.dumps(
                {
                    "passed": False,
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
