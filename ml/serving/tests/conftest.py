"""Shared pytest fixtures and trained-model factory for ML serving tests."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

from ml.common.artifact_contract import UncertaintyConfigContract
from ml.common.preprocessing import build_features, build_preprocessor
from ml.serving.config import ServingSettings
from ml.serving.model_loader import ModelRegistryHolder
from ml.serving.predictor import TrainedModelPredictor


def build_trained_sklearn_pipeline() -> tuple[Pipeline, UncertaintyConfigContract]:
    """Train a fast, deterministic sklearn Pipeline on synthetic PaySim rows.

    Returns a real fitted `Pipeline(preprocessor, LogisticRegression)` and an
    `UncertaintyConfigContract` so all serving tests run through the true
    ML inference and split-conformal pipeline without heuristic shortcuts.
    """
    rows = [
        # Legitimate low-drain payments/transfers
        {
            "type": "PAYMENT",
            "amount": 120.0,
            "sender_old_balance": 5000.0,
            "sender_new_balance": 4880.0,
            "receiver_old_balance": 200.0,
            "receiver_new_balance": 320.0,
        },
        {
            "type": "CASH_IN",
            "amount": 500.0,
            "sender_old_balance": 1000.0,
            "sender_new_balance": 1500.0,
            "receiver_old_balance": 3000.0,
            "receiver_new_balance": 2500.0,
        },
        {
            "type": "DEBIT",
            "amount": 45.0,
            "sender_old_balance": 900.0,
            "sender_new_balance": 855.0,
            "receiver_old_balance": 100.0,
            "receiver_new_balance": 145.0,
        },
        {
            "type": "PAYMENT",
            "amount": 80.0,
            "sender_old_balance": 2500.0,
            "sender_new_balance": 2420.0,
            "receiver_old_balance": 0.0,
            "receiver_new_balance": 80.0,
        },
        # Fraudulent full-drain transfers/cash-outs
        {
            "type": "TRANSFER",
            "amount": 250000.0,
            "sender_old_balance": 250000.0,
            "sender_new_balance": 0.0,
            "receiver_old_balance": 0.0,
            "receiver_new_balance": 250000.0,
        },
        {
            "type": "CASH_OUT",
            "amount": 180000.0,
            "sender_old_balance": 180000.0,
            "sender_new_balance": 0.0,
            "receiver_old_balance": 500.0,
            "receiver_new_balance": 180500.0,
        },
        {
            "type": "TRANSFER",
            "amount": 95000.0,
            "sender_old_balance": 95000.0,
            "sender_new_balance": 0.0,
            "receiver_old_balance": 0.0,
            "receiver_new_balance": 0.0,
        },
        {
            "type": "CASH_OUT",
            "amount": 420000.0,
            "sender_old_balance": 420000.0,
            "sender_new_balance": 0.0,
            "receiver_old_balance": 1200.0,
            "receiver_new_balance": 421200.0,
        },
    ]
    labels = [0, 0, 0, 0, 1, 1, 1, 1]
    feature_df = build_features(pd.DataFrame(rows))

    pipeline = Pipeline(
        steps=[
            ("preprocessor", build_preprocessor()),
            ("classifier", LogisticRegression(C=5.0, max_iter=200, random_state=42)),
        ]
    )
    pipeline.fit(feature_df, labels)

    uncertainty_config = UncertaintyConfigContract(
        method="split_conformal",
        confidence_level=0.95,
        target_review_rate=0.05,
        q_hat_fraud=0.65,
        q_hat_legit=0.65,
    )
    return pipeline, uncertainty_config


@pytest.fixture
def trained_predictor() -> TrainedModelPredictor:
    pipeline, uncertainty_config = build_trained_sklearn_pipeline()
    return TrainedModelPredictor(
        model=pipeline,
        uncertainty_config=uncertainty_config,
        model_name="fraud-detector",
        model_version="3",
        model_alias="production",
        run_id="run-fixture-0003",
    )


@pytest.fixture
def test_settings(tmp_path: Path) -> ServingSettings:
    viz_dir = tmp_path / "viz"
    viz_dir.mkdir(parents=True, exist_ok=True)
    return ServingSettings(
        environment="test",
        startup_load_enabled=False,
        viz_data_dir=viz_dir,
        internal_api_key=None,
    )


@pytest.fixture
def loaded_holder(
    test_settings: ServingSettings, trained_predictor: TrainedModelPredictor
) -> ModelRegistryHolder:
    holder = ModelRegistryHolder(test_settings)
    holder.set_predictor(trained_predictor, load_seconds=0.12)
    return holder
