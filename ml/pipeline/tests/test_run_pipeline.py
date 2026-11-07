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
    """Validate that --synthetic mode is strictly smoke-only: logs no statistical_validation.json and never promotes to @staging or @production."""
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

    # @candidate must exist for smoke verification
    mv_cand = client.get_model_version_by_alias(REGISTERED_MODEL_NAME, CANDIDATE_ALIAS)

    # Run must carry data_source=synthetic and uncertainty_config_sha256
    run = client.get_run(mv_cand.run_id)
    assert run.data.tags.get(DATA_SOURCE_TAG) == "synthetic"
    assert len(run.data.tags.get(UNCERTAINTY_SHA256_TAG, "")) == 64

    # Synthetic smoke run MUST NOT log statistical_validation.json
    artifact_paths = [a.path for a in client.list_artifacts(mv_cand.run_id)]
    assert "statistical_validation.json" not in artifact_paths

    # Neither @staging nor @production may exist for a synthetic smoke run
    with pytest.raises(MlflowException):
        client.get_model_version_by_alias(REGISTERED_MODEL_NAME, STAGING_ALIAS)
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

    # 2. _extract_champion_metrics must fail if any required metric is missing, boolean, or non-finite
    with pytest.raises(PipelineInfraError, match="Refusing to fabricate"):
        _extract_champion_metrics({"metrics_summary": {"roc_auc": 0.99}})

    boolean_summary = {
        key: True if key == "roc_auc" else 0.5
        for key in (
            "roc_auc",
            "pr_auc",
            "f1",
            "precision",
            "recall",
            "mcc",
            "brier_score",
            "coverage_legit",
            "coverage_fraud",
            "expected_review_rate",
            "inference_p95_ms",
        )
    }
    with pytest.raises(PipelineInfraError, match="Refusing to fabricate"):
        _extract_champion_metrics({"metrics_summary": boolean_summary})

    non_finite_summary = {
        **boolean_summary,
        "roc_auc": float("inf"),
    }
    with pytest.raises(PipelineInfraError, match="Refusing to fabricate"):
        _extract_champion_metrics({"metrics_summary": non_finite_summary})

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
    import json
    import zipfile

    import joblib
    import numpy as np
    import pandas as pd
    from sklearn.pipeline import Pipeline
    from xgboost import XGBClassifier

    from ml.common.preprocessing import build_features, build_preprocessor
    from ml.common.schema import TRANSACTION_TYPES
    from ml.pipeline.fetch_model import extract_and_verify_archive
    from ml.pipeline.mlflow_config import PipelineInfraError
    from ml.pipeline.populate_mlflow import UNCERTAINTY_JSON_PATH

    with open(UNCERTAINTY_JSON_PATH, "r", encoding="utf-8") as f:
        real_config = json.load(f)

    # 1. Unfitted pipeline in archive MUST be rejected by load_champion_pipeline
    unfitted_pipe = Pipeline(
        steps=[
            ("preprocessor", build_preprocessor()),
            ("classifier", XGBClassifier(n_estimators=2, max_depth=2, random_state=42)),
        ]
    )
    unfitted_buf = io.BytesIO()
    joblib.dump({"pipeline": unfitted_pipe, "config": real_config}, unfitted_buf)
    unfitted_bytes = unfitted_buf.getvalue()
    unfitted_inner_sha = hashlib.sha256(unfitted_bytes).hexdigest()

    unfitted_zip_buf = io.BytesIO()
    with zipfile.ZipFile(unfitted_zip_buf, "w") as zf:
        zf.writestr(
            "fraud-detector-paysim-v9.9.9/model/final_contract_model.joblib",
            unfitted_bytes,
        )
        zf.writestr(
            "fraud-detector-paysim-v9.9.9/SHA256SUMS",
            f"{unfitted_inner_sha}  model/final_contract_model.joblib\n",
        )
    unfitted_zip_bytes = unfitted_zip_buf.getvalue()
    out_path = tmp_path / "processed" / "final_contract_model.joblib"

    with pytest.raises(PipelineInfraError, match="not fitted"):
        extract_and_verify_archive(
            zip_bytes=unfitted_zip_bytes,
            expected_zip_sha256=hashlib.sha256(unfitted_zip_bytes).hexdigest(),
            output_path=out_path,
        )
    assert not out_path.exists()

    # 2. Build a fitted contract XGBoost pipeline covering all 5 transaction types
    sample_rows = [
        {
            "type": tx_type,
            "amount": 100.0 + idx * 10.0,
            "sender_old_balance": 1000.0,
            "sender_new_balance": 900.0 - idx * 10.0,
            "receiver_old_balance": 500.0,
            "receiver_new_balance": 600.0 + idx * 10.0,
        }
        for idx, tx_type in enumerate(TRANSACTION_TYPES * 2)
    ]
    y_sample = np.array([idx % 2 for idx in range(len(sample_rows))], dtype=int)
    fitted_pipe = Pipeline(
        steps=[
            ("preprocessor", build_preprocessor()),
            (
                "classifier",
                XGBClassifier(
                    n_estimators=2,
                    max_depth=2,
                    random_state=42,
                    eval_metric="logloss",
                ),
            ),
        ]
    )
    fitted_pipe.fit(build_features(pd.DataFrame(sample_rows)), y_sample)

    model_buf = io.BytesIO()
    joblib.dump({"pipeline": fitted_pipe, "config": real_config}, model_buf)
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

    # 3. Outer SHA-256 mismatch must fail strictly
    with pytest.raises(PipelineInfraError, match="Archive SHA-256 mismatch"):
        extract_and_verify_archive(
            zip_bytes=zip_bytes,
            expected_zip_sha256="0" * 64,
            output_path=out_path,
        )


def test_load_champion_pipeline_rejects_config_mismatch(tmp_path: Path) -> None:
    """Validate that load_champion_pipeline strictly rejects artifacts whose embedded config disagrees with uncertainty_config.json."""
    import json

    import joblib
    import numpy as np
    import pandas as pd
    from sklearn.pipeline import Pipeline
    from xgboost import XGBClassifier

    from ml.common.preprocessing import build_features, build_preprocessor
    from ml.common.schema import TRANSACTION_TYPES
    from ml.pipeline.mlflow_config import PipelineInfraError
    from ml.pipeline.populate_mlflow import (
        UNCERTAINTY_JSON_PATH,
        load_champion_pipeline,
    )

    real_config = json.loads(UNCERTAINTY_JSON_PATH.read_text(encoding="utf-8"))

    sample_rows = [
        {
            "type": tx_type,
            "amount": 100.0 + idx * 10.0,
            "sender_old_balance": 1000.0,
            "sender_new_balance": 900.0 - idx * 10.0,
            "receiver_old_balance": 500.0,
            "receiver_new_balance": 600.0 + idx * 10.0,
        }
        for idx, tx_type in enumerate(TRANSACTION_TYPES * 2)
    ]
    y_sample = np.array([idx % 2 for idx in range(len(sample_rows))], dtype=int)
    fitted_pipe = Pipeline(
        steps=[
            ("preprocessor", build_preprocessor()),
            (
                "classifier",
                XGBClassifier(
                    n_estimators=2,
                    max_depth=2,
                    random_state=42,
                    eval_metric="logloss",
                ),
            ),
        ]
    )
    fitted_pipe.fit(build_features(pd.DataFrame(sample_rows)), y_sample)

    # 1. Valid coupled artifact (matching UNCERTAINTY_JSON_PATH) MUST succeed
    valid_path = tmp_path / "valid_model.joblib"
    joblib.dump({"pipeline": fitted_pipe, "config": real_config}, valid_path)
    loaded_pipe = load_champion_pipeline(local_model_path=valid_path)
    assert isinstance(loaded_pipe, Pipeline)

    # 2. Tampered embedded config (q_hat_fraud = 0.999) MUST be rejected by default
    bad_config = dict(real_config)
    bad_config["q_hat_fraud"] = 0.999
    tampered_path = tmp_path / "tampered_model.joblib"
    joblib.dump({"pipeline": fitted_pipe, "config": bad_config}, tampered_path)

    with pytest.raises(
        PipelineInfraError, match="embedded uncertainty config mismatch"
    ):
        load_champion_pipeline(local_model_path=tampered_path)

    # 3. Bare Pipeline without embedded config dict MUST also be rejected
    bare_path = tmp_path / "bare_pipeline.joblib"
    joblib.dump(fitted_pipe, bare_path)
    with pytest.raises(PipelineInfraError, match="Invalid model structure"):
        load_champion_pipeline(local_model_path=bare_path)


def test_resolve_release_assets_filters_model_release_and_pairs_stem(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Validate that resolve_release_assets ignores non-model latest releases and correctly pairs by stem."""
    import json

    from ml.pipeline import fetch_model
    from ml.pipeline.fetch_model import resolve_release_assets
    from ml.pipeline.mlflow_config import PipelineInfraError

    mock_releases = [
        {
            "tag_name": "v2.0.0",
            "draft": False,
            "assets": [
                {
                    "name": "backend.zip",
                    "browser_download_url": "https://example.com/backend.zip",
                },
                {
                    "name": "backend.zip.sha256",
                    "browser_download_url": "https://example.com/backend.zip.sha256",
                },
            ],
        },
        {
            "tag_name": "model-v1.0.0",
            "draft": False,
            "assets": [
                {
                    "name": "dataset.zip",
                    "browser_download_url": "https://example.com/dataset.zip",
                },
                {
                    "name": "dataset.zip.sha256",
                    "browser_download_url": "https://example.com/dataset.zip.sha256",
                },
                {
                    "name": "fraud-detector-paysim-v1.0.0.zip",
                    "browser_download_url": "https://example.com/model.zip",
                },
                {
                    "name": "fraud-detector-paysim-v1.0.0.zip.sha256",
                    "browser_download_url": "https://example.com/model.zip.sha256",
                },
            ],
        },
    ]

    def mock_http_get_bytes(
        url: str, *, accept: str = "application/octet-stream"
    ) -> bytes:
        return json.dumps(mock_releases).encode("utf-8")

    monkeypatch.setattr(fetch_model, "_http_get_bytes", mock_http_get_bytes)

    tag, zip_url, sha_url = resolve_release_assets(repo="test/repo", tag="latest")
    assert tag == "model-v1.0.0"
    assert zip_url == "https://example.com/model.zip"
    assert sha_url == "https://example.com/model.zip.sha256"

    # Explicit non-model tag must be rejected immediately
    with pytest.raises(PipelineInfraError, match="Invalid model release tag"):
        resolve_release_assets(repo="test/repo", tag="v2.0.0")
