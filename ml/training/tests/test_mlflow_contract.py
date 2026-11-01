"""Contract tests for the MLOps promotion flow and statistics export."""
from __future__ import annotations

import json

from ml.common.artifact_contract import (
    CANDIDATE_ALIAS,
    DATA_SOURCE,
    PRODUCTION_ALIAS,
    REQUIRED_RUN_TAGS,
    STAGING_ALIAS,
)
from ml.training.scripts.run_statistics import write_json


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
    assert payload["metrics"] == ["pr_auc"]
    finding = payload["findings"][0]
    assert finding["friedman_p"] == 0.4563
    assert finding["pairs"][0]["raw_p"] == 0.5047
    assert finding["pairs"][0]["holm_p"] == 0.5047
