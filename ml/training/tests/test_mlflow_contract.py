"""Contract tests for the MLOps promotion flow and statistics export."""
from __future__ import annotations

import json

import pandas as pd
import pytest

from ml.common.artifact_contract import (
    CANDIDATE_ALIAS,
    DATA_SOURCE,
    PRODUCTION_ALIAS,
    REQUIRED_RUN_TAGS,
    STAGING_ALIAS,
)
from ml.training.scripts.run_statistics import validate_benchmark, write_json


def test_promotion_aliases_and_tags() -> None:
    assert CANDIDATE_ALIAS == "candidate"
    assert STAGING_ALIAS == "staging"
    assert PRODUCTION_ALIAS == "production"
    assert DATA_SOURCE == "paysim"
    assert "data_source" in REQUIRED_RUN_TAGS
    assert "uncertainty_config_sha256" in REQUIRED_RUN_TAGS


def test_statistics_json_contains_friedman_and_holm(tmp_path) -> None:
    findings = [
        {
            "population": "app_valid",
            "protocol": "contract",
            "metric": "pr_auc",
            "blocks": 15,
            "models": ["lr", "xgb"],
            "friedman_p": 0.4563,
            "pairs": [
                {
                    "model_a": "lr",
                    "model_b": "xgb",
                    "mean_diff": -0.0001,
                    "ci_low": -0.0002,
                    "ci_high": 0.0000,
                    "raw_p": 0.5047,
                    "holm_p": 0.5047,
                    "effect": -0.227,
                }
            ],
        }
    ]
    path = write_json(
        findings,
        tmp_path / "statistical_validation.json",
        results_path=tmp_path / "benchmark_runs.csv",
        metrics=["pr_auc"],
    )
    payload = json.loads(path.read_text())
    assert payload["schema_version"] == "1.0"
    assert payload["results_csv"] == "benchmark_runs.csv"
    assert not payload["results_csv"].startswith("/")
    assert payload["metrics"] == ["pr_auc"]
    finding = payload["findings"][0]
    assert finding["friedman_p"] == 0.4563
    assert finding["pairs"][0]["raw_p"] == 0.5047
    assert finding["pairs"][0]["holm_p"] == 0.5047


def _results_frame() -> pd.DataFrame:
    rows = []
    for protocol in ("contract", "restricted", "rule_blind"):
        for model in ("lr", "xgb"):
            for fold in range(2):
                for seed in (42, 43):
                    rows.append(
                        {
                            "population": "app_valid",
                            "protocol": protocol,
                            "model": model,
                            "fold": fold,
                            "seed": seed,
                            "pr_auc": 0.9,
                        }
                    )
    return pd.DataFrame(rows)


def test_validate_benchmark_rejects_incomplete_runs() -> None:
    frame = _results_frame()
    validate_benchmark(
        frame,
        expected_models=["lr", "xgb"],
        expected_protocols=["contract", "restricted", "rule_blind"],
        expected_blocks=4,
    )

    with pytest.raises(ValueError, match="missing models"):
        validate_benchmark(
            frame[frame["model"] != "xgb"],
            expected_models=["lr", "xgb"],
            expected_protocols=["contract", "restricted", "rule_blind"],
            expected_blocks=4,
        )
    with pytest.raises(ValueError, match="expected 5"):
        validate_benchmark(
            frame,
            expected_models=["lr", "xgb"],
            expected_protocols=["contract", "restricted", "rule_blind"],
            expected_blocks=5,
        )
    # Exploratory partial runs can opt out explicitly.
    validate_benchmark(
        frame[frame["model"] == "lr"],
        expected_models=["lr", "xgb"],
        expected_protocols=["contract"],
        expected_blocks=99,
        allow_partial=True,
    )
