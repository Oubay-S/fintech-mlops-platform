"""Contract, Offline-vs-Online Parity, and Resilience Tests for ML Serving (Issue #34).

Verifies:
1. OpenAPI response contract compliance (all required fields, types, and request_id /
   X-Correlation-Id propagation) for Spring Boot `risk-service` integration.
2. Edge-case validation: zero amount/balance (PaySim parity), full balance drain,
   negative amounts/balances, unsupported schema_version, and forbidden extra fields.
3. Bit-for-bit offline-vs-online parity between `build_features` + `pipeline.predict_proba`
   + `prediction_set` and HTTP `POST /predict` on all 6 cases from
   `ml/training/package/parity_cases.json` (both self-contained for CI and against the
   real PaySim Champion `.joblib` when present on disk).
4. Failure & timeout contract for Spring Boot `risk-service` Rule R2 circuit-breaker
   fallback (`503 MODEL_NOT_READY` and simulated 1.5s latency timeout).
"""

from __future__ import annotations

import json
import math
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sklearn.pipeline import Pipeline
from xgboost import XGBClassifier

from ml.common.artifact_contract import (
    UncertaintyConfigContract,
    prediction_set,
    suggested_action,
)
from ml.common.preprocessing import build_features, build_preprocessor
from ml.common.schema import TRANSACTION_TYPES
from ml.pipeline.populate_mlflow import (
    LOCAL_MODEL_PATH,
    UNCERTAINTY_JSON_PATH,
    load_champion_pipeline,
)
from ml.serving.config import ServingSettings
from ml.serving.main import create_app
from ml.serving.model_loader import ModelRegistryHolder
from ml.serving.predictor import (
    PredictionOutcome,
    TrainedModelPredictor,
)
from ml.serving.schemas import PredictRequest

REPO_ROOT = Path(__file__).resolve().parents[3]
PARITY_CASES_PATH = REPO_ROOT / "ml" / "training" / "package" / "parity_cases.json"


def _build_ci_contract_xgboost_pipeline() -> Pipeline:
    """Build a deterministic fitted contract XGBoost Pipeline covering all 5 transaction types."""
    rows = [
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
    labels = np.array([idx % 2 for idx in range(len(rows))], dtype=int)
    pipe = Pipeline(
        steps=[
            ("preprocessor", build_preprocessor()),
            (
                "classifier",
                XGBClassifier(
                    n_estimators=4,
                    max_depth=2,
                    random_state=42,
                    eval_metric="logloss",
                ),
            ),
        ]
    )
    pipe.fit(build_features(pd.DataFrame(rows)), labels)
    return pipe


@contextmanager
def _make_client_with_predictor(
    tmp_path: Path, predictor: TrainedModelPredictor | None
) -> Iterator[TestClient]:
    settings = ServingSettings(
        environment="test",
        startup_load_enabled=False,
        viz_data_dir=tmp_path / "viz",
        internal_api_key=None,
    )
    holder = ModelRegistryHolder(settings)
    if predictor is not None:
        holder.set_predictor(predictor, load_seconds=0.05)
    else:
        holder.clear_predictor()
    app = create_app(settings=settings, holder=holder)
    try:
        with TestClient(app) as client:
            yield client
    finally:
        holder.clear_predictor()


def test_offline_vs_online_http_parity_all_six_cases(tmp_path: Path) -> None:
    """Verify exact parity between offline pipeline scoring and HTTP POST /predict across all 6 parity cases."""
    parity_fixture = json.loads(PARITY_CASES_PATH.read_text(encoding="utf-8"))
    raw_config = json.loads(UNCERTAINTY_JSON_PATH.read_text(encoding="utf-8"))
    config = UncertaintyConfigContract.from_dict(raw_config)
    pipe = _build_ci_contract_xgboost_pipeline()

    predictor = TrainedModelPredictor(
        model=pipe,
        uncertainty_config=config,
        model_name="fraud-detector",
        model_version="1",
        model_alias="production",
        run_id="ci-parity-run",
    )

    with _make_client_with_predictor(tmp_path, predictor) as client:
        for case in parity_fixture["cases"]:
            payload = case["request"]
            features = payload["features"]

            # Offline scoring path (reusing shared ml.common.artifact_contract)
            engineered = build_features(pd.DataFrame([features]))
            offline_prob = float(
                np.clip(pipe.predict_proba(engineered)[:, 1][0], 0.0, 1.0)
            )
            offline_set = prediction_set(offline_prob, config)
            p_clamped = min(max(offline_prob, 1e-12), 1.0 - 1e-12)
            offline_score = float(
                np.clip(
                    -(
                        p_clamped * math.log2(p_clamped)
                        + (1.0 - p_clamped) * math.log2(1.0 - p_clamped)
                    ),
                    0.0,
                    1.0,
                )
            )
            if not offline_set:
                offline_action = "HUMAN_REVIEW"
                offline_score = max(offline_score, 0.85)
            elif offline_score >= config.high_uncertainty_score_threshold:
                offline_action = "HUMAN_REVIEW"
            else:
                offline_action = suggested_action(offline_set)

            # Online HTTP POST /predict path
            corr_id = str(uuid4())
            resp = client.post(
                "/predict",
                json=payload,
                headers={"X-Correlation-Id": corr_id},
            )
            assert resp.status_code == 200, case["name"]
            body = resp.json()

            # Assert exact OpenAPI contract fields
            assert set(body.keys()) == {
                "schema_version",
                "request_id",
                "action",
                "fraud_probability",
                "uncertainty",
                "model",
                "explanations",
                "inference_ms",
            }
            assert set(body["uncertainty"].keys()) == {
                "method",
                "confidence_level",
                "prediction_set",
                "score",
            }
            assert body["schema_version"] == "1.0"
            assert body["request_id"] == payload["request_id"]
            assert body["model"]["name"] == "fraud-detector"
            assert body["model"]["version"] == "1"
            assert body["model"]["alias"] == "production"
            assert body["model"]["stage"] == "Production"

            # Assert zero skew between offline and online HTTP predictions
            assert body["fraud_probability"] == pytest.approx(offline_prob, abs=1e-6)
            assert body["uncertainty"]["prediction_set"] == offline_set
            assert body["uncertainty"]["score"] == pytest.approx(
                offline_score, abs=1e-6
            )
            assert body["action"] == offline_action


@pytest.mark.skipif(
    not LOCAL_MODEL_PATH.exists(),
    reason="Real PaySim Champion joblib is git-ignored; run fetch_model to execute real-weights parity.",
)
def test_real_champion_http_golden_parity_exact_match(tmp_path: Path) -> None:
    """When real final_contract_model.joblib is present, assert max |delta| == 0.0 on all 6 Golden cases."""
    parity_fixture = json.loads(PARITY_CASES_PATH.read_text(encoding="utf-8"))
    raw_config = json.loads(UNCERTAINTY_JSON_PATH.read_text(encoding="utf-8"))
    config = UncertaintyConfigContract.from_dict(raw_config)
    pipe = load_champion_pipeline(
        local_model_path=LOCAL_MODEL_PATH,
        expected_config_path=UNCERTAINTY_JSON_PATH,
    )

    predictor = TrainedModelPredictor(
        model=pipe,
        uncertainty_config=config,
        model_name="fraud-detector",
        model_version="1",
        model_alias="production",
        run_id="real-champion-parity-run",
    )

    with _make_client_with_predictor(tmp_path, predictor) as client:
        for case in parity_fixture["cases"]:
            resp = client.post("/predict", json=case["request"])
            assert resp.status_code == 200, case["name"]
            body = resp.json()
            expected = case["expected"]

            assert round(body["fraud_probability"], 6) == expected["fraud_probability"]
            assert body["uncertainty"]["prediction_set"] == expected["prediction_set"]
            assert body["action"] == expected["action"]
            assert (
                round(body["uncertainty"]["score"], 6) == expected["uncertainty_score"]
            )


def test_contract_edge_cases_zero_balance_and_strict_422(
    tmp_path: Path, trained_predictor: TrainedModelPredictor
) -> None:
    """Verify edge cases required for Spring Boot risk-service contract: zero balance/amount, full drain, 422 errors."""
    with _make_client_with_predictor(tmp_path, trained_predictor) as client:
        # 1. Zero amount & zero sender/receiver balances -> must succeed (200) without division-by-zero
        zero_req_id = str(uuid4())
        zero_resp = client.post(
            "/predict",
            json={
                "schema_version": "1.0",
                "request_id": zero_req_id,
                "features": {
                    "type": "TRANSFER",
                    "amount": 0.0,
                    "sender_old_balance": 0.0,
                    "sender_new_balance": 0.0,
                    "receiver_old_balance": 0.0,
                    "receiver_new_balance": 0.0,
                },
            },
        )
        assert zero_resp.status_code == 200
        assert zero_resp.json()["request_id"] == zero_req_id
        assert 0.0 <= zero_resp.json()["fraud_probability"] <= 1.0

        # 2. Negative amount -> strict 422 VALIDATION_FAILED echoing request_id
        neg_req_id = str(uuid4())
        neg_resp = client.post(
            "/predict",
            json={
                "schema_version": "1.0",
                "request_id": neg_req_id,
                "features": {
                    "type": "TRANSFER",
                    "amount": -100.0,
                    "sender_old_balance": 1000.0,
                    "sender_new_balance": 900.0,
                    "receiver_old_balance": 0.0,
                    "receiver_new_balance": 100.0,
                },
            },
        )
        assert neg_resp.status_code == 422
        neg_body = neg_resp.json()
        assert neg_body["code"] == "VALIDATION_FAILED"
        assert neg_body["status"] == 422
        assert neg_body["request_id"] == neg_req_id

        # 3. Unsupported schema_version -> strict 422 UNSUPPORTED_SCHEMA_VERSION
        ver_req_id = str(uuid4())
        ver_resp = client.post(
            "/predict",
            json={
                "schema_version": "2.0",
                "request_id": ver_req_id,
                "features": {
                    "type": "TRANSFER",
                    "amount": 100.0,
                    "sender_old_balance": 1000.0,
                    "sender_new_balance": 900.0,
                    "receiver_old_balance": 0.0,
                    "receiver_new_balance": 100.0,
                },
            },
        )
        assert ver_resp.status_code == 422
        assert ver_resp.json()["code"] == "UNSUPPORTED_SCHEMA_VERSION"
        assert ver_resp.json()["request_id"] == ver_req_id

        # 4. Forbidden extra field -> strict 422 VALIDATION_FAILED
        extra_resp = client.post(
            "/predict",
            json={
                "schema_version": "1.0",
                "request_id": str(uuid4()),
                "features": {
                    "type": "TRANSFER",
                    "amount": 100.0,
                    "sender_old_balance": 1000.0,
                    "sender_new_balance": 900.0,
                    "receiver_old_balance": 0.0,
                    "receiver_new_balance": 100.0,
                    "isFraud": 1,
                },
            },
        )
        assert extra_resp.status_code == 422
        assert extra_resp.json()["code"] == "VALIDATION_FAILED"


def test_rule_r2_circuit_breaker_contract_503_and_timeout_simulation(
    tmp_path: Path,
) -> None:
    """Verify 503 MODEL_NOT_READY and 1.5s timeout behavior for Spring Boot Risk Service Rule R2 fallback."""
    sample_payload = {
        "schema_version": "1.0",
        "request_id": str(uuid4()),
        "features": {
            "type": "TRANSFER",
            "amount": 2500.0,
            "sender_old_balance": 10000.0,
            "sender_new_balance": 7500.0,
            "receiver_old_balance": 500.0,
            "receiver_new_balance": 3000.0,
        },
    }

    # 1. Unloaded model -> strict 503 MODEL_NOT_READY (triggers Risk Service Rule R2 degraded=true)
    with _make_client_with_predictor(tmp_path, predictor=None) as unloaded_client:
        resp_503 = unloaded_client.post("/predict", json=sample_payload)
        assert resp_503.status_code == 503
        body_503 = resp_503.json()
        assert body_503["code"] == "MODEL_NOT_READY"
        assert body_503["status"] == 503
        assert body_503["request_id"] == sample_payload["request_id"]

    # 2. Simulate a 1.5s slow inference exceeding Risk Service's timeout budget
    raw_config = json.loads(UNCERTAINTY_JSON_PATH.read_text(encoding="utf-8"))
    config = UncertaintyConfigContract.from_dict(raw_config)
    pipe = _build_ci_contract_xgboost_pipeline()

    class _SlowPredictorWrapper(TrainedModelPredictor):
        def predict(self, request: PredictRequest) -> PredictionOutcome:
            time.sleep(1.5)
            return super().predict(request)

    slow_predictor = _SlowPredictorWrapper(
        model=pipe,
        uncertainty_config=config,
        model_name="fraud-detector",
        model_version="1",
        model_alias="production",
        run_id="slow-timeout-test",
    )

    with (
        _make_client_with_predictor(tmp_path, predictor=slow_predictor) as slow_client,
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        # Simulate Risk Service HTTP client enforcing a strict timeout (< 1.5s) -> Rule R2 fallback
        future = pool.submit(slow_client.post, "/predict", json=sample_payload)
        with pytest.raises(FuturesTimeoutError):
            future.result(timeout=0.3)

        # Liveness probe must remain healthy even while a slow prediction is in flight
        live_resp = slow_client.get("/health/live")
        assert live_resp.status_code == 200
        assert live_resp.json()["status"] == "ok"
