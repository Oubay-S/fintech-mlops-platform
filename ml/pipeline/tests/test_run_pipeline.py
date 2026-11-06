"""Tests for `ml/pipeline/run_pipeline.py` and atomic serving startup integration."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from ml.common.artifact_contract import (
    CANDIDATE_ALIAS,
    DATA_SOURCE_TAG,
    PRODUCTION_ALIAS,
    REGISTERED_MODEL_NAME,
    STAGING_ALIAS,
    UNCERTAINTY_SHA256_TAG,
)
from ml.pipeline.mlflow_config import (
    EXIT_INFRA_ERROR,
    EXIT_SUCCESS,
)
from ml.pipeline.promote_model import main as promote_main
from ml.pipeline.run_pipeline import generate_synthetic_paysim_df
from ml.pipeline.run_pipeline import main as pipeline_main
from ml.serving.config import ServingSettings
from ml.serving.model_loader import MLflowModelLoader
from ml.serving.schemas import PredictRequest, TransactionFeatures, TransactionType

from .conftest import create_isolated_mlflow_uri


def test_run_pipeline_refuses_silent_fallback_when_csv_missing_exit_2(
    tmp_path: Path,
) -> None:
    tracking_uri = create_isolated_mlflow_uri(tmp_path)

    # 1. Missing both --data-path and --synthetic -> exit 2
    assert pipeline_main(["--tracking-uri", tracking_uri]) == EXIT_INFRA_ERROR

    # 2. Non-existent CSV path without --synthetic -> exit 2
    missing_csv = tmp_path / "does_not_exist.csv"
    assert (
        pipeline_main(
            [
                "--data-path",
                str(missing_csv),
                "--tracking-uri",
                tracking_uri,
            ]
        )
        == EXIT_INFRA_ERROR
    )


def test_run_pipeline_synthetic_mode_sets_staging_and_never_production(
    tmp_path: Path,
) -> None:
    mlflow = pytest.importorskip("mlflow")
    from mlflow.exceptions import MlflowException
    from mlflow.tracking import MlflowClient

    tracking_uri = create_isolated_mlflow_uri(tmp_path)
    code = pipeline_main(
        [
            "--synthetic",
            "--synthetic-rows",
            "300",
            "--tracking-uri",
            tracking_uri,
        ]
    )
    assert code == EXIT_SUCCESS

    mlflow.set_tracking_uri(tracking_uri)
    client = MlflowClient(tracking_uri=tracking_uri)

    # @candidate and @staging must exist
    mv_cand = client.get_model_version_by_alias(REGISTERED_MODEL_NAME, CANDIDATE_ALIAS)
    mv_stag = client.get_model_version_by_alias(REGISTERED_MODEL_NAME, STAGING_ALIAS)
    assert str(mv_cand.version) == str(mv_stag.version)

    # Run must carry data_source=synthetic and uncertainty_config_sha256
    run = client.get_run(mv_stag.run_id)
    assert run.data.tags.get(DATA_SOURCE_TAG) == "synthetic"
    assert len(run.data.tags.get(UNCERTAINTY_SHA256_TAG, "")) == 64

    # @production MUST NOT exist
    with pytest.raises(MlflowException):
        client.get_model_version_by_alias(REGISTERED_MODEL_NAME, PRODUCTION_ALIAS)


def test_run_pipeline_csv_mode_and_serving_atomic_sha256_startup(
    tmp_path: Path,
) -> None:
    pytest.importorskip("mlflow")
    from mlflow.tracking import MlflowClient

    tracking_uri = create_isolated_mlflow_uri(tmp_path)

    # Write a valid PaySim CSV file to tmp_path
    csv_path = tmp_path / "paysim_sample.csv"
    df = generate_synthetic_paysim_df(n_rows=300, seed=42)
    df.to_csv(csv_path, index=False)

    # 1. Run nominal pipeline with --data-path (tags data_source=paysim -> @staging)
    assert (
        pipeline_main(
            [
                "--data-path",
                str(csv_path),
                "--tracking-uri",
                tracking_uri,
            ]
        )
        == EXIT_SUCCESS
    )

    # 2. Explicitly promote @staging -> @production
    assert (
        promote_main(
            [
                "--from-alias",
                "staging",
                "--to-alias",
                "production",
                "--tracking-uri",
                tracking_uri,
            ]
        )
        == EXIT_SUCCESS
    )

    # 3. New FastAPI MLflowModelLoader instance loads @production at startup and verifies SHA-256
    settings = ServingSettings(
        mlflow_tracking_uri=tracking_uri,
        model_name=REGISTERED_MODEL_NAME,
        model_alias=PRODUCTION_ALIAS,
        startup_load_enabled=False,
    )
    loader = MLflowModelLoader(settings)
    predictor = loader.load_by_alias()

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
    assert outcome.response.model.name == REGISTERED_MODEL_NAME
    assert outcome.response.model.alias.value == PRODUCTION_ALIAS
    assert outcome.response.action.value == "BLOCK"

    # 4. Tamper with the run's uncertainty_config_sha256 tag and verify loader rejects it
    client = MlflowClient(tracking_uri=tracking_uri)
    mv_prod = client.get_model_version_by_alias(REGISTERED_MODEL_NAME, PRODUCTION_ALIAS)
    client.set_tag(mv_prod.run_id, UNCERTAINTY_SHA256_TAG, "deadbeef" * 8)

    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        loader.load_by_alias()


def test_populate_mlflow_strict_no_fallback_when_model_or_metrics_missing(
    tmp_path: Path,
) -> None:
    import numpy as np
    import pandas as pd

    from ml.common.artifact_contract import UncertaintyConfigContract
    from ml.pipeline.conformal_eval import evaluate_existing_thresholds_on_split
    from ml.pipeline.mlflow_config import PipelineInfraError
    from ml.pipeline.populate_mlflow import (
        _extract_benchmark_metrics,
        _extract_champion_metrics,
        load_champion_pipeline,
    )
    from ml.pipeline.populate_mlflow import (
        main as populate_main,
    )

    # 1. Missing model file must raise PipelineInfraError (exit code 2), never build a surrogate
    missing_model = tmp_path / "missing_final_contract_model.joblib"
    with pytest.raises(PipelineInfraError, match="No surrogate or fallback model"):
        load_champion_pipeline(local_model_path=missing_model)

    assert populate_main(["--model-path", str(missing_model)]) == EXIT_INFRA_ERROR

    # 2. _extract_champion_metrics must fail if any required metric is missing
    with pytest.raises(PipelineInfraError, match="Refusing to fabricate"):
        _extract_champion_metrics({"metrics_summary": {"roc_auc": 0.99}})

    # 3. _extract_benchmark_metrics must not fabricate inference_p95_ms and must fail on missing model
    df = pd.DataFrame(
        [
            {
                "protocol": "contract",
                "model": "lr",
                "roc_auc": 0.96,
                "pr_auc": 0.85,
                "f1": 0.80,
                "precision": 0.82,
                "recall": 0.78,
                "mcc": 0.79,
                "brier": 0.02,
                "predict_ms_per_row": 0.005,
            }
        ]
    )
    lr_metrics = _extract_benchmark_metrics(df, "lr")
    assert "inference_p95_ms" not in lr_metrics
    with pytest.raises(PipelineInfraError, match="No benchmark rows found"):
        _extract_benchmark_metrics(df, "svm")

    # 4. evaluate_existing_thresholds_on_split must raise ValueError if a class is absent
    dummy_cfg = UncertaintyConfigContract(
        method="mondrian_conformal",
        confidence_level=0.99,
        q_hat_fraud=0.01,
        q_hat_legit=0.01,
    )
    with pytest.raises(ValueError, match="Both legitimate"):
        evaluate_existing_thresholds_on_split(
            p_fraud=np.array([0.001, 0.002]),
            y_true=np.array([0, 0]),
            config=dummy_cfg,
        )


def test_fetch_model_extract_and_verify_archive_strict(tmp_path: Path) -> None:
    import hashlib
    import io
    import zipfile

    import joblib
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline

    from ml.common.preprocessing import build_preprocessor
    from ml.pipeline.fetch_model import extract_and_verify_archive
    from ml.pipeline.mlflow_config import PipelineInfraError

    # Build a valid contract pipeline and serialize to bytes
    pipe = Pipeline(
        steps=[
            ("preprocessor", build_preprocessor()),
            ("classifier", LogisticRegression()),
        ]
    )
    model_buf = io.BytesIO()
    joblib.dump({"pipeline": pipe, "config": {}}, model_buf)
    model_bytes = model_buf.getvalue()
    inner_sha = hashlib.sha256(model_bytes).hexdigest()

    # Package inside an archive with an arbitrary future release folder name (v9.9.9)
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as zf:
        zf.writestr(
            "fraud-detector-paysim-v9.9.9/model/final_contract_model.joblib",
            model_bytes,
        )
        zf.writestr(
            "fraud-detector-paysim-v9.9.9/SHA256SUMS",
            f"{inner_sha}  model/final_contract_model.joblib\n",
        )
    zip_bytes = zip_buf.getvalue()
    outer_sha = hashlib.sha256(zip_bytes).hexdigest()

    out_path = tmp_path / "processed" / "final_contract_model.joblib"
    saved = extract_and_verify_archive(
        zip_bytes=zip_bytes,
        expected_zip_sha256=outer_sha,
        output_path=out_path,
    )
    assert saved == out_path
    assert out_path.exists()
    # Ensure no extra directories were created next to final_contract_model.joblib
    assert [p.name for p in out_path.parent.iterdir()] == [
        "final_contract_model.joblib"
    ]

    # Outer SHA-256 mismatch must fail strictly
    with pytest.raises(PipelineInfraError, match="Archive SHA-256 mismatch"):
        extract_and_verify_archive(
            zip_bytes=zip_bytes,
            expected_zip_sha256="0" * 64,
            output_path=out_path,
        )
