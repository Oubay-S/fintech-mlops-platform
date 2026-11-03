"""Training-serving feature parity against the serving golden fixture.

This is the Role 4 side of the serving parity contract: it verifies that
``build_features`` accepts both PaySim and contract-named frames, that the
preprocessor always emits the 14-column golden signature (five fixed types),
and that the serving's ``UncertaintyConfigContract`` validates our metadata.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ml.common.artifact_contract import (
    EXPECTED_TRANSFORMED_FEATURES,
    UncertaintyConfigContract,
)
from ml.common.preprocessing import build_features, build_preprocessor
from ml.common.schema import FEATURE_COLUMNS

GOLDEN_PATH = Path(__file__).parent / "fixtures" / "golden_features.json"


def test_golden_feature_parity() -> None:
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    assert golden["feature_columns"] == list(FEATURE_COLUMNS)
    assert golden["transformed_feature_names"] == list(EXPECTED_TRANSFORMED_FEATURES)

    for case in golden["cases"]:
        raw = build_features(pd.DataFrame([case["raw_paysim"]]))[list(FEATURE_COLUMNS)]
        contract = build_features(pd.DataFrame([case["contract_input"]]))[
            list(FEATURE_COLUMNS)
        ]
        expected = case["expected_engineered"]
        assert raw.iloc[0]["type"] == expected["type"], case["name"]
        assert contract.iloc[0]["type"] == expected["type"], case["name"]
        for column in FEATURE_COLUMNS[1:]:
            np.testing.assert_allclose(
                float(raw.iloc[0][column]),
                float(expected[column]),
                rtol=1e-9,
                atol=1e-12,
                err_msg=f"raw mismatch {case['name']}.{column}",
            )
            np.testing.assert_allclose(
                float(contract.iloc[0][column]),
                float(expected[column]),
                rtol=1e-9,
                atol=1e-12,
                err_msg=f"contract mismatch {case['name']}.{column}",
            )
            np.testing.assert_allclose(
                float(contract.iloc[0][column]),
                float(raw.iloc[0][column]),
                rtol=1e-12,
                atol=1e-12,
                err_msg=f"raw-vs-contract skew {case['name']}.{column}",
            )


def test_preprocessor_golden_signature() -> None:
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    features = build_features(
        pd.DataFrame([case["raw_paysim"] for case in golden["cases"]])
    )[list(FEATURE_COLUMNS)]
    preprocessor = build_preprocessor()
    transformed = preprocessor.fit_transform(features)
    assert transformed.shape == (len(golden["cases"]), 14)
    assert list(preprocessor.get_feature_names_out()) == list(EXPECTED_TRANSFORMED_FEATURES)


def test_uncertainty_config_contract() -> None:
    config = UncertaintyConfigContract(
        confidence_level=0.99,
        q_hat_fraud=0.000118,
        q_hat_legit=0.000053,
        feature_names=list(FEATURE_COLUMNS),
        transformed_feature_names=list(EXPECTED_TRANSFORMED_FEATURES),
        model_feature_names=list(EXPECTED_TRANSFORMED_FEATURES),
    )
    config.validate()
    with pytest.raises(ValueError, match="Feature signature mismatch"):
        UncertaintyConfigContract(feature_names=["amount", "type"]).validate()
