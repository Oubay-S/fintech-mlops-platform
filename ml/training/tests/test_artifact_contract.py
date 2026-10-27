"""Tests for the MLflow artifact contract and the serving-safe feature path."""
from __future__ import annotations

import pandas as pd
import pytest

from ml.common.artifact_contract import (
    UncertaintyConfig,
    prediction_set,
    suggested_action,
)
from ml.common.paths import ML_DIR
from ml.common.preprocessing import build_features, build_serving_features


def _config() -> UncertaintyConfig:
    return UncertaintyConfig(
        confidence_level=0.99,
        q_hat_fraud=0.5191,
        q_hat_legit=0.00007,
        target_review_rate=0.05,
        algorithm="LogisticRegression",
        model_feature_names=["amount", "sender_old_balance", "type_TRANSFER"],
    )


def test_serving_features_match_training_features() -> None:
    raw = pd.DataFrame(
        {
            "type": ["TRANSFER"],
            "amount": [1000.0],
            "oldbalanceOrg": [1000.0],
            "newbalanceOrig": [0.0],
            "oldbalanceDest": [0.0],
            "newbalanceDest": [1000.0],
        }
    )
    contract = raw.rename(
        columns={
            "oldbalanceOrg": "sender_old_balance",
            "newbalanceOrig": "sender_new_balance",
            "oldbalanceDest": "receiver_old_balance",
            "newbalanceDest": "receiver_new_balance",
        }
    )
    training = build_features(raw)
    serving = build_serving_features(contract)
    assert list(training.columns) == list(serving.columns)
    pd.testing.assert_frame_equal(training, serving)


def test_prediction_set_cases() -> None:
    config = _config()
    assert prediction_set(0.99999, config) == ["fraud"]
    assert prediction_set(0.00007, config) == ["legit"]
    assert prediction_set(0.4, config) == []  # 1 - 0.4 > 0.5191, p > 0.00007
    # Both classes included when the scores are inside both thresholds.
    both = UncertaintyConfig(confidence_level=0.99, q_hat_fraud=0.7, q_hat_legit=0.5)
    assert prediction_set(0.4, both) == ["legit", "fraud"]
    # Empty set when neither class meets its threshold.
    empty = UncertaintyConfig(confidence_level=0.99, q_hat_fraud=0.01, q_hat_legit=0.01)
    assert prediction_set(0.9, empty) == []


def test_suggested_action() -> None:
    assert suggested_action(["fraud"]) == "BLOCK"
    assert suggested_action(["legit"]) == "ALLOW"
    assert suggested_action(["legit", "fraud"]) == "HUMAN_REVIEW"
    assert suggested_action([]) == "HUMAN_REVIEW"


def test_config_round_trip(tmp_path) -> None:
    config = _config()
    config.validate()
    payload = config.to_dict()
    restored = UncertaintyConfig.from_dict(payload)
    assert restored.to_dict() == payload

    path = config.save(tmp_path / "uncertainty_config.json")
    loaded = UncertaintyConfig.load(path)
    assert loaded.to_dict() == payload


def test_config_validation() -> None:
    with pytest.raises(ValueError):
        UncertaintyConfig(confidence_level=0.4, q_hat_fraud=0.5, q_hat_legit=0.1).validate()
    with pytest.raises(ValueError):
        UncertaintyConfig(confidence_level=0.99, q_hat_fraud=1.1, q_hat_legit=0.1).validate()
    with pytest.raises(ValueError):
        UncertaintyConfig(
            confidence_level=0.99, q_hat_fraud=0.5, q_hat_legit=0.1, contract_features=[]
        ).validate()


def test_prediction_set_rejects_invalid_probability() -> None:
    with pytest.raises(ValueError):
        prediction_set(1.1, _config())


def test_example_config_loads() -> None:
    path = ML_DIR / "training" / "docs" / "uncertainty_config.example.json"
    config = UncertaintyConfig.load(path)
    assert config.confidence_level == 0.99
    assert config.eval_population == "app-valid TRANSFER+CASH_OUT"
    assert len(config.model_feature_names) == 14
