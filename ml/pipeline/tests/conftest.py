"""Shared fixtures and MLflow test helpers for `ml/pipeline/tests/`."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

from ml.common.artifact_contract import (
    CANDIDATE_ALIAS,
    DATA_SOURCE_TAG,
    DEFAULT_EXPERIMENT_NAME,
    EXPECTED_TRANSFORMED_FEATURES,
    MODEL_ARTIFACT_PATH,
    REGISTERED_MODEL_NAME,
    STATISTICAL_VALIDATION_ARTIFACT,
    UNCERTAINTY_CONFIG_ARTIFACT,
    UNCERTAINTY_SHA256_TAG,
    UncertaintyConfigContract,
)
from ml.common.preprocessing import build_features, build_preprocessor


def create_isolated_mlflow_uri(tmp_path: Path, subdir: str = "mlflow") -> str:
    """Create an isolated SQLite-backed MLflow tracking URI inside `tmp_path`."""
    mlflow = pytest.importorskip("mlflow")
    from mlflow.tracking import MlflowClient

    base = tmp_path / subdir
    base.mkdir(parents=True, exist_ok=True)
    db_path = base / "mlflow.db"
    artifacts_dir = base / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    tracking_uri = f"sqlite:///{db_path.as_posix()}"
    mlflow.set_tracking_uri(tracking_uri)
    client = MlflowClient(tracking_uri=tracking_uri)
    if client.get_experiment_by_name(DEFAULT_EXPERIMENT_NAME) is None:
        client.create_experiment(
            DEFAULT_EXPERIMENT_NAME,
            artifact_location=artifacts_dir.as_uri(),
        )
    return tracking_uri


def build_fitted_test_pipeline() -> Pipeline:
    """Build a fast fitted 14-column sklearn Pipeline (`build_preprocessor` + `LogisticRegression`)."""
    rows = [
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
            "type": "TRANSFER",
            "amount": 80.0,
            "sender_old_balance": 2500.0,
            "sender_new_balance": 2420.0,
            "receiver_old_balance": 0.0,
            "receiver_new_balance": 80.0,
        },
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
    ]
    labels = [0, 0, 0, 0, 1, 1]
    features_df = build_features(pd.DataFrame(rows))
    pipeline = Pipeline(
        steps=[
            ("preprocessor", build_preprocessor()),
            ("classifier", LogisticRegression(C=5.0, max_iter=200, random_state=42)),
        ]
    )
    pipeline.fit(features_df, labels)
    return pipeline


def log_test_candidate_run(
    tracking_uri: str,
    *,
    data_source: str = "paysim",
    metrics_override: dict[str, float] | None = None,
    stat_override: dict[str, Any] | None = None,
    log_stat_artifact: bool = True,
    log_uncertainty_artifact: bool = True,
    sha256_tag_override: str | None = None,
    set_candidate_alias: bool = True,
) -> tuple[str, str]:
    """Log a candidate model run to `tracking_uri` and return `(run_id, version_str)`."""
    import mlflow
    from mlflow.tracking import MlflowClient

    mlflow.set_tracking_uri(tracking_uri)
    client = MlflowClient(tracking_uri=tracking_uri)
    exp = client.get_experiment_by_name(DEFAULT_EXPERIMENT_NAME)
    assert exp is not None

    pipeline = build_fitted_test_pipeline()
    default_metrics: dict[str, float] = {
        "roc_auc": 0.9990,
        "pr_auc": 0.9975,
        "f1": 0.9950,
        "precision": 0.9980,
        "recall": 0.9920,
        "mcc": 0.9940,
        "brier_score": 0.0001,
        "expected_review_rate": 0.0180,
        "coverage_legit": 0.9910,
        "coverage_fraud": 0.9896,
        "inference_p95_ms": 6.5,
    }
    if metrics_override:
        default_metrics.update(metrics_override)

    uncertainty_cfg = UncertaintyConfigContract(
        method="mondrian_conformal",
        confidence_level=0.99,
        target_review_rate=0.05,
        q_hat_fraud=0.60,
        q_hat_legit=0.85,
        algorithm="LogisticRegression",
        transformed_feature_names=list(EXPECTED_TRANSFORMED_FEATURES),
        metrics_summary=default_metrics,
    )
    computed_sha = uncertainty_cfg.sha256()

    stat_payload: dict[str, Any] = {
        "schema_version": "1.0",
        "friedman_p": 0.0001,
        "min_holm_p": 0.0006,
        "wilcoxon_holm_significant": True,
    }
    if stat_override is not None:
        stat_payload = stat_override

    with mlflow.start_run(experiment_id=exp.experiment_id) as run:
        run_id = str(run.info.run_id)
        tags = {
            "algorithm": "LogisticRegression",
            "dataset_version": "paysim-v1",
            "git_sha": "abc123456789",
            "seed": "42",
            DATA_SOURCE_TAG: data_source,
            UNCERTAINTY_SHA256_TAG: (
                sha256_tag_override if sha256_tag_override is not None else computed_sha
            ),
        }
        mlflow.set_tags(tags)
        mlflow.log_metrics(default_metrics)
        if log_uncertainty_artifact:
            mlflow.log_dict(uncertainty_cfg.to_dict(), UNCERTAINTY_CONFIG_ARTIFACT)
        if log_stat_artifact:
            mlflow.log_dict(stat_payload, STATISTICAL_VALIDATION_ARTIFACT)

        mlflow.sklearn.log_model(
            sk_model=pipeline,
            artifact_path=MODEL_ARTIFACT_PATH,
            registered_model_name=REGISTERED_MODEL_NAME,
            serialization_format="cloudpickle",
        )

    versions = client.search_model_versions(f"name='{REGISTERED_MODEL_NAME}'")
    version_str = next(
        (str(v.version) for v in versions if str(v.run_id) == run_id),
        str(versions[0].version),
    )
    if set_candidate_alias:
        client.set_registered_model_alias(
            name=REGISTERED_MODEL_NAME,
            alias=CANDIDATE_ALIAS,
            version=version_str,
        )
    return run_id, version_str
