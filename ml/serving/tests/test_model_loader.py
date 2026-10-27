"""Tests for isolated `MLflowModelLoader` using a temporary local MLflow store.

Logs a real `sklearn` Pipeline (`build_preprocessor()` + `LogisticRegression`) and
`uncertainty_config.json` to `tmp_path`, sets alias `production`, and verifies
`MLflowModelLoader.load_by_alias()` and `ModelRegistryHolder`.
"""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from ml.common.artifact_contract import (
    MODEL_ARTIFACT_PATH,
    PRODUCTION_ALIAS,
    REGISTERED_MODEL_NAME,
    UNCERTAINTY_CONFIG_ARTIFACT,
)
from ml.serving.config import ServingSettings
from ml.serving.model_loader import MLflowModelLoader, ModelRegistryHolder
from ml.serving.schemas import PredictRequest, TransactionFeatures, TransactionType

from .conftest import build_trained_sklearn_pipeline


def _log_model_to_tmp_mlflow(tmp_path: Path) -> str:
    mlflow = pytest.importorskip("mlflow")
    from mlflow.tracking import MlflowClient

    db_path = tmp_path / "mlflow.db"
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    tracking_uri = f"sqlite:///{db_path.as_posix()}"

    mlflow.set_tracking_uri(tracking_uri)
    client = MlflowClient(tracking_uri=tracking_uri)

    exp_id = client.create_experiment(
        "test-paysim-experiment",
        artifact_location=artifacts_dir.as_uri(),
    )

    pipeline, uncertainty_config = build_trained_sklearn_pipeline()

    with mlflow.start_run(experiment_id=exp_id) as run:
        mlflow.log_dict(uncertainty_config.to_dict(), UNCERTAINTY_CONFIG_ARTIFACT)
        mlflow.sklearn.log_model(
            sk_model=pipeline,
            artifact_path=MODEL_ARTIFACT_PATH,
            registered_model_name=REGISTERED_MODEL_NAME,
            serialization_format="cloudpickle",
        )
        run_id = run.info.run_id

    versions = client.search_model_versions(f"name='{REGISTERED_MODEL_NAME}'")
    assert len(versions) >= 1
    latest_version = str(versions[0].version)

    client.set_registered_model_alias(
        name=REGISTERED_MODEL_NAME,
        alias=PRODUCTION_ALIAS,
        version=latest_version,
    )
    assert run_id is not None
    return tracking_uri


def test_mlflow_model_loader_loads_by_production_alias(tmp_path: Path) -> None:
    tracking_uri = _log_model_to_tmp_mlflow(tmp_path)

    settings = ServingSettings(
        mlflow_tracking_uri=tracking_uri,
        model_name=REGISTERED_MODEL_NAME,
        model_alias=PRODUCTION_ALIAS,
        startup_load_enabled=False,
    )
    loader = MLflowModelLoader(settings)
    predictor = loader.load_by_alias()

    model_ref = predictor.get_model_ref()
    assert model_ref.name == REGISTERED_MODEL_NAME
    assert model_ref.alias.value == PRODUCTION_ALIAS
    assert model_ref.stage.value == "Production"

    req = PredictRequest(
        schema_version="1.0",
        request_id=uuid4(),
        features=TransactionFeatures(
            type=TransactionType.TRANSFER,
            amount=250000.0,
            sender_old_balance=250000.0,
            sender_new_balance=0.0,
            receiver_old_balance=0.0,
            receiver_new_balance=250000.0,
        ),
    )
    outcome = predictor.predict(req)
    assert outcome.response.request_id == req.request_id
    assert outcome.response.action.value == "BLOCK"
    assert [p.value for p in outcome.response.uncertainty.prediction_set] == ["fraud"]


def test_holder_background_resilience_when_mlflow_unreachable(tmp_path: Path) -> None:
    settings = ServingSettings(
        mlflow_tracking_uri=f"sqlite:///{(tmp_path / 'empty.db').as_posix()}",
        model_name="nonexistent-model",
        model_alias="production",
        startup_load_enabled=True,
        loader_initial_backoff_seconds=0.05,
        loader_max_backoff_seconds=0.1,
        loader_max_attempts=2,
    )
    holder = ModelRegistryHolder(settings)
    assert not holder.is_ready
    assert holder.try_load_once() is False
    assert not holder.is_ready
