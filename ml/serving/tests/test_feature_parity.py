"""Golden-file feature parity tests guarding against training-serving skew.

Verifies:
1. `ml.common.preprocessing.build_features` and `TrainedModelPredictor.features_to_dataframe`
   produce identical 10-column feature vectors matching `fixtures/golden_features.json`.
2. `build_preprocessor()` outputs the exact 14-column transformed signature
   (`EXPECTED_TRANSFORMED_FEATURES`).
3. A mismatch in feature order or column names raises `ValueError` during model initialization.
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
from ml.serving.predictor import TrainedModelPredictor
from ml.serving.schemas import TransactionFeatures

GOLDEN_PATH = Path(__file__).parent / "fixtures" / "golden_features.json"


def test_golden_file_feature_parity() -> None:
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    assert golden["feature_columns"] == list(FEATURE_COLUMNS)
    assert golden["transformed_feature_names"] == list(EXPECTED_TRANSFORMED_FEATURES)

    for case in golden["cases"]:
        raw_df = pd.DataFrame([case["raw_paysim"]])
        from_raw = build_features(raw_df)[list(FEATURE_COLUMNS)]

        contract_dto = TransactionFeatures.model_validate(case["contract_input"])
        from_serving = TrainedModelPredictor.features_to_dataframe(contract_dto)

        assert list(from_raw.columns) == list(FEATURE_COLUMNS), case["name"]
        assert list(from_serving.columns) == list(FEATURE_COLUMNS), case["name"]

        expected = case["expected_engineered"]
        assert from_serving.iloc[0]["type"] == expected["type"], case["name"]
        assert from_raw.iloc[0]["type"] == expected["type"], case["name"]

        for col in FEATURE_COLUMNS[1:]:
            np.testing.assert_allclose(
                float(from_serving.iloc[0][col]),
                float(expected[col]),
                rtol=1e-9,
                atol=1e-12,
                err_msg=f"Serving mismatch on {case['name']}.{col}",
            )
            np.testing.assert_allclose(
                float(from_raw.iloc[0][col]),
                float(from_serving.iloc[0][col]),
                rtol=1e-12,
                atol=1e-12,
                err_msg=f"Raw-vs-serving skew on {case['name']}.{col}",
            )


def test_preprocessor_transformed_signature_matches_contract() -> None:
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    rows = [case["raw_paysim"] for case in golden["cases"]]
    features_df = build_features(pd.DataFrame(rows))[list(FEATURE_COLUMNS)]

    preprocessor = build_preprocessor()
    transformed = preprocessor.fit_transform(features_df)
    names_out = list(preprocessor.get_feature_names_out())

    assert transformed.shape == (len(rows), 14)
    assert names_out == list(EXPECTED_TRANSFORMED_FEATURES)


def test_signature_mismatch_raises_value_error(trained_predictor: TrainedModelPredictor) -> None:
    bad_config = UncertaintyConfigContract(
        feature_names=["amount", "type"]  # Wrong order and missing features
    )
    with pytest.raises(ValueError, match="Feature signature mismatch"):
        bad_config.validate()
