"""Guards for the generated serving package (parity fixture + artifacts).

These tests are intentionally data-light: they read the committed package
under ``ml/training/package`` so a stale or hand-edited artifact fails CI.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from ml.common.artifact_contract import (
    EXPECTED_TRANSFORMED_FEATURES,
    UncertaintyConfig,
    prediction_set,
)
from ml.common.paths import ML_DIR
from ml.common.preprocessing import to_contract_frame
from ml.common.schema import CONTRACT_FEATURES, DERIVED_FEATURES, FEATURE_COLUMNS

PACKAGE = ML_DIR / "training" / "package"


def test_package_config_matches_contract() -> None:
    config = UncertaintyConfig.load(PACKAGE / "uncertainty_config.json")
    assert list(config.feature_names) == list(FEATURE_COLUMNS)
    assert list(config.transformed_feature_names) == list(EXPECTED_TRANSFORMED_FEATURES)
    assert config.feature_names == list(CONTRACT_FEATURES + DERIVED_FEATURES)
    assert config.confidence_level == 0.99
    assert config.method == "mondrian_conformal"


def test_parity_fixture_is_complete_and_consistent() -> None:
    payload = json.loads((PACKAGE / "parity_cases.json").read_text())
    assert payload["model"] == "fraud-detector"
    assert len(payload["cases"]) >= 6

    actions = {case["expected"]["action"] for case in payload["cases"]}
    assert actions == {"ALLOW", "BLOCK", "HUMAN_REVIEW"}

    empty_set_cases = [
        case for case in payload["cases"] if case["expected"]["prediction_set"] == []
    ]
    assert empty_set_cases, "parity fixture must exercise the empty-set review path"
    for case in empty_set_cases:
        # ML Serving floors empty-set uncertainty at 0.85.
        assert case["expected"]["uncertainty_score"] == 0.85

    for case in payload["cases"]:
        request = case["request"]
        assert request["schema_version"] == "1.0"
        assert set(request["features"]) == set(CONTRACT_FEATURES)
        expected = case["expected"]
        assert set(expected) == {
            "fraud_probability",
            "prediction_set",
            "action",
            "uncertainty_score",
        }
        assert 0.0 <= expected["fraud_probability"] <= 1.0
        assert 0.0 <= expected["uncertainty_score"] <= 1.0


def test_prediction_set_matches_fixture_expectations() -> None:
    config = UncertaintyConfig.load(PACKAGE / "uncertainty_config.json")
    payload = json.loads((PACKAGE / "parity_cases.json").read_text())
    for case in payload["cases"]:
        expected = case["expected"]
        labels = prediction_set(expected["fraud_probability"], config)
        assert labels == expected["prediction_set"], case["name"]


def test_model_card_reflects_final_metrics() -> None:
    card = (PACKAGE / "model_card.md").read_text()
    config = UncertaintyConfig.load(PACKAGE / "uncertainty_config.json")
    assert "1.322%" in card
    assert "0.935%" in card
    assert "0.387%" in card
    assert "98.47%" in card
    assert f"{float(config.metrics_summary['expected_review_rate']) * 100:.3f}%" in card


def test_to_contract_frame_drops_extras_and_rejects_partial() -> None:
    contract = pd.DataFrame(
        [
            {
                "type": "TRANSFER",
                "amount": 10.0,
                "sender_old_balance": 100.0,
                "sender_new_balance": 90.0,
                "receiver_old_balance": 0.0,
                "receiver_new_balance": 10.0,
                "step": 1,
                "nameOrig": "C1",
            }
        ]
    )
    mapped = to_contract_frame(contract)
    assert list(mapped.columns) == list(CONTRACT_FEATURES)
    assert "step" not in mapped.columns

    partial = contract.drop(columns=["receiver_new_balance"])
    with pytest.raises(ValueError, match="Missing PaySim columns"):
        to_contract_frame(partial)
