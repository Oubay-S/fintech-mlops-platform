"""Tests for `ml/pipeline/validate_gate.py` and `ml/pipeline/conformal_eval.py`."""

from __future__ import annotations

from pathlib import Path

from ml.pipeline.conformal_eval import main as conformal_main
from ml.pipeline.mlflow_config import (
    EXIT_GATE_FAILURE,
    EXIT_INFRA_ERROR,
    EXIT_SUCCESS,
)
from ml.pipeline.validate_gate import main as gate_main

from .conftest import create_isolated_mlflow_uri, log_test_candidate_run


def test_validate_gate_passes_valid_candidate_exit_0(tmp_path: Path) -> None:
    tracking_uri = create_isolated_mlflow_uri(tmp_path)
    run_id, _ = log_test_candidate_run(tracking_uri)

    code_by_alias = gate_main(["--alias", "candidate", "--tracking-uri", tracking_uri])
    assert code_by_alias == EXIT_SUCCESS

    code_by_run = gate_main(["--run-id", run_id, "--tracking-uri", tracking_uri])
    assert code_by_run == EXIT_SUCCESS

    conf_code = conformal_main(["--alias", "candidate", "--tracking-uri", tracking_uri])
    assert conf_code == EXIT_SUCCESS


def test_validate_gate_fails_on_scalar_or_latency_or_review_budget_exit_1(
    tmp_path: Path,
) -> None:
    tracking_uri = create_isolated_mlflow_uri(tmp_path)

    # 1. Low PR-AUC (< 0.90) -> exit 1
    log_test_candidate_run(
        tracking_uri,
        metrics_override={"pr_auc": 0.72},
    )
    assert (
        gate_main(["--alias", "candidate", "--tracking-uri", tracking_uri])
        == EXIT_GATE_FAILURE
    )

    # 2. High review rate (> 0.05) -> exit 1
    log_test_candidate_run(
        tracking_uri,
        metrics_override={"expected_review_rate": 0.085},
    )
    assert (
        gate_main(["--alias", "candidate", "--tracking-uri", tracking_uri])
        == EXIT_GATE_FAILURE
    )

    # 3. Latency p95 >= 300ms -> exit 1
    log_test_candidate_run(
        tracking_uri,
        metrics_override={"inference_p95_ms": 340.0},
    )
    assert (
        gate_main(["--alias", "candidate", "--tracking-uri", tracking_uri])
        == EXIT_GATE_FAILURE
    )


def test_validate_gate_fails_on_statistical_validation_exit_1(tmp_path: Path) -> None:
    tracking_uri = create_isolated_mlflow_uri(tmp_path)

    # Friedman p-value >= 0.05 (null hypothesis not rejected) -> exit 1
    log_test_candidate_run(
        tracking_uri,
        stat_override={
            "friedman_p": 0.42,
            "min_holm_p": 0.001,
            "wilcoxon_holm_significant": True,
        },
    )
    assert (
        gate_main(["--alias", "candidate", "--tracking-uri", tracking_uri])
        == EXIT_GATE_FAILURE
    )

    # Wilcoxon/Holm not significant -> exit 1
    log_test_candidate_run(
        tracking_uri,
        stat_override={
            "friedman_p": 0.001,
            "min_holm_p": 0.25,
            "wilcoxon_holm_significant": False,
        },
    )
    assert (
        gate_main(["--alias", "candidate", "--tracking-uri", tracking_uri])
        == EXIT_GATE_FAILURE
    )


def test_validate_gate_fails_on_conformal_coverage_or_sha256_mismatch_exit_1(
    tmp_path: Path,
) -> None:
    tracking_uri = create_isolated_mlflow_uri(tmp_path)

    # Low empirical fraud coverage (< 0.99 - 0.005 = 0.985) -> exit 1
    log_test_candidate_run(
        tracking_uri,
        metrics_override={"coverage_fraud": 0.91},
    )
    assert (
        gate_main(["--alias", "candidate", "--tracking-uri", tracking_uri])
        == EXIT_GATE_FAILURE
    )

    # Corrupted SHA-256 tag -> exit 1
    log_test_candidate_run(
        tracking_uri,
        sha256_tag_override="0000000000000000000000000000000000000000000000000000000000000000",
    )
    assert (
        gate_main(["--alias", "candidate", "--tracking-uri", tracking_uri])
        == EXIT_GATE_FAILURE
    )


def test_validate_gate_returns_exit_2_on_missing_alias_or_missing_artifact(
    tmp_path: Path,
) -> None:
    tracking_uri = create_isolated_mlflow_uri(tmp_path)

    # Alias does not exist yet -> exit 2 (INFRA_ERROR)
    assert (
        gate_main(["--alias", "nonexistent_alias", "--tracking-uri", tracking_uri])
        == EXIT_INFRA_ERROR
    )

    # Missing statistical_validation.json artifact -> exit 2 (INFRA_ERROR)
    log_test_candidate_run(
        tracking_uri,
        log_stat_artifact=False,
    )
    assert (
        gate_main(["--alias", "candidate", "--tracking-uri", tracking_uri])
        == EXIT_INFRA_ERROR
    )
