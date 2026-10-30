"""Comprehensive functional, readiness, security, validation, metrics, and latency test suite."""
from __future__ import annotations

import json
import time
from uuid import uuid4

import numpy as np
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from ml.common.artifact_contract import UncertaintyConfigContract
from ml.serving.config import ServingSettings
from ml.serving.main import create_app
from ml.serving.model_loader import ModelRegistryHolder
from ml.serving.predictor import TrainedModelPredictor
from ml.serving.schemas import (
    PredictRequest,
    TransactionFeatures,
    TransactionType,
)

from .conftest import build_trained_sklearn_pipeline


# ---------------------------------------------------------------------------
# 1. Strict ML-Only Readiness (503 when model is NOT loaded)
# ---------------------------------------------------------------------------
def test_strict_503_when_model_not_loaded(test_settings: ServingSettings) -> None:
    empty_holder = ModelRegistryHolder(test_settings)
    app = create_app(settings=test_settings, holder=empty_holder)
    client = TestClient(app)

    # /health/live and /health ALWAYS return 200
    live_resp = client.get("/health/live")
    assert live_resp.status_code == 200
    assert live_resp.json()["status"] == "ok"
    assert live_resp.json()["model_version"] is None

    alias_live = client.get("/health")
    assert alias_live.status_code == 200
    assert alias_live.json() == live_resp.json()

    # /health/ready and /ready return 503 ErrorResponse (MODEL_NOT_READY)
    req_id = str(uuid4())
    ready_resp = client.get("/health/ready", headers={"X-Request-ID": req_id})
    assert ready_resp.status_code == 503
    body = ready_resp.json()
    assert body["code"] == "MODEL_NOT_READY"
    assert body["request_id"] == req_id
    assert body["status"] == 503
    assert ready_resp.headers["X-Request-ID"] == req_id

    alias_ready = client.get("/ready", headers={"X-Request-ID": req_id})
    assert alias_ready.status_code == 503
    assert alias_ready.json() == ready_resp.json()

    # /model-info returns 503 ErrorResponse (MODEL_NOT_READY)
    info_resp = client.get("/model-info", headers={"X-Request-ID": req_id})
    assert info_resp.status_code == 503
    assert info_resp.json()["code"] == "MODEL_NOT_READY"

    # /predict returns 503 ErrorResponse (MODEL_NOT_READY) with body request_id echoed
    pred_id = str(uuid4())
    pred_resp = client.post(
        "/predict",
        json={
            "schema_version": "1.0",
            "request_id": pred_id,
            "features": {
                "type": "TRANSFER",
                "amount": 100.0,
                "sender_old_balance": 1000.0,
                "sender_new_balance": 900.0,
                "receiver_old_balance": 100.0,
                "receiver_new_balance": 200.0,
            },
        },
    )
    assert pred_resp.status_code == 503
    assert pred_resp.json()["code"] == "MODEL_NOT_READY"
    assert pred_resp.json()["request_id"] == pred_id
    assert pred_resp.headers["X-Request-ID"] == pred_id

    # Gauge ml_ready is 0.0
    metrics_text = client.get("/metrics").text
    assert "ml_ready 0.0" in metrics_text


# ---------------------------------------------------------------------------
# 2. Predictions & Conformal Sets When Trained Model Is Loaded
# ---------------------------------------------------------------------------
def test_health_and_model_info_when_loaded(
    test_settings: ServingSettings, loaded_holder: ModelRegistryHolder
) -> None:
    app = create_app(settings=test_settings, holder=loaded_holder)
    client = TestClient(app)

    ready = client.get("/health/ready")
    assert ready.status_code == 200
    assert ready.json()["ready"] is True
    assert ready.json()["model"]["version"] == "3"
    assert ready.json()["model"]["alias"] == "production"

    alias_ready = client.get("/ready")
    assert alias_ready.status_code == 200
    assert alias_ready.json() == ready.json()

    info = client.get("/model-info")
    assert info.status_code == 200
    info_json = info.json()
    assert info_json["model"]["name"] == "fraud-detector"
    assert info_json["model"]["version"] == "3"
    assert info_json["model"]["run_id"] == "run-fixture-0003"
    assert info_json["conformal_config"]["method"] == "split_conformal"
    assert len(info_json["contract_features"]) == 6
    assert len(info_json["derived_features"]) == 4


def test_predict_confident_legit_allow(
    test_settings: ServingSettings, loaded_holder: ModelRegistryHolder
) -> None:
    app = create_app(settings=test_settings, holder=loaded_holder)
    client = TestClient(app)
    req_id = str(uuid4())

    resp = client.post(
        "/predict",
        json={
            "schema_version": "1.0",
            "request_id": req_id,
            "features": {
                "type": "TRANSFER",
                "amount": 120.0,
                "sender_old_balance": 5000.0,
                "sender_new_balance": 4880.0,
                "receiver_old_balance": 200.0,
                "receiver_new_balance": 320.0,
            },
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["request_id"] == req_id
    assert resp.headers["X-Request-ID"] == req_id
    assert data["action"] == "ALLOW"
    assert data["uncertainty"]["prediction_set"] == ["legit"]
    assert 0.0 <= data["fraud_probability"] < 0.35
    assert data["model"]["version"] == "3"


def test_predict_confident_fraud_block(
    test_settings: ServingSettings, loaded_holder: ModelRegistryHolder
) -> None:
    app = create_app(settings=test_settings, holder=loaded_holder)
    client = TestClient(app)
    req_id = str(uuid4())

    resp = client.post(
        "/predict",
        json={
            "schema_version": "1.0",
            "request_id": req_id,
            "features": {
                "type": "TRANSFER",
                "amount": 250000.0,
                "sender_old_balance": 250000.0,
                "sender_new_balance": 0.0,
                "receiver_old_balance": 0.0,
                "receiver_new_balance": 250000.0,
            },
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["request_id"] == req_id
    assert data["action"] == "BLOCK"
    assert data["uncertainty"]["prediction_set"] == ["fraud"]
    assert data["fraud_probability"] > 0.65
    assert data["explanations"] is not None
    assert len(data["explanations"]) > 0


def test_predict_uncertain_ambiguous_and_empty_sets(test_settings: ServingSettings) -> None:
    pipeline, _ = build_trained_sklearn_pipeline()

    # 1. Ambiguous conformal thresholds (both q_hat_legit and q_hat_fraud = 0.999 -> ["legit", "fraud"])
    ambiguous_cfg = UncertaintyConfigContract(
        q_hat_fraud=0.999,
        q_hat_legit=0.999,
    )
    ambiguous_predictor = TrainedModelPredictor(
        model=pipeline,
        uncertainty_config=ambiguous_cfg,
        model_name="fraud-detector",
        model_version="4",
        model_alias="production",
    )
    holder = ModelRegistryHolder(test_settings)
    holder.set_predictor(ambiguous_predictor, load_seconds=0.05)
    client = TestClient(create_app(settings=test_settings, holder=holder))

    resp = client.post(
        "/predict",
        json={
            "schema_version": "1.0",
            "request_id": str(uuid4()),
            "features": {
                "type": "TRANSFER",
                "amount": 50000.0,
                "sender_old_balance": 60000.0,
                "sender_new_balance": 10000.0,
                "receiver_old_balance": 1000.0,
                "receiver_new_balance": 51000.0,
            },
        },
    )
    assert resp.status_code == 200
    assert resp.json()["action"] == "HUMAN_REVIEW"
    assert resp.json()["uncertainty"]["prediction_set"] == ["legit", "fraud"]

    # 2. Tight conformal thresholds producing an empty prediction set []
    empty_cfg = UncertaintyConfigContract(
        q_hat_fraud=0.0001,
        q_hat_legit=0.0001,
    )
    empty_predictor = TrainedModelPredictor(
        model=pipeline,
        uncertainty_config=empty_cfg,
        model_name="fraud-detector",
        model_version="5",
        model_alias="production",
    )
    holder.set_predictor(empty_predictor, load_seconds=0.05)

    resp_empty = client.post(
        "/predict",
        json={
            "schema_version": "1.0",
            "request_id": str(uuid4()),
            "features": {
                "type": "CASH_OUT",
                "amount": 80000.0,
                "sender_old_balance": 100000.0,
                "sender_new_balance": 20000.0,
                "receiver_old_balance": 5000.0,
                "receiver_new_balance": 85000.0,
            },
        },
    )
    assert resp_empty.status_code == 200
    assert resp_empty.json()["action"] == "HUMAN_REVIEW"
    assert resp_empty.json()["uncertainty"]["prediction_set"] == []


# ---------------------------------------------------------------------------
# 3. Security: X-Internal-Api-Key (401 without it; probes and /metrics exempt)
# ---------------------------------------------------------------------------
def test_internal_api_key_security_and_probe_exemptions(
    trained_predictor: TrainedModelPredictor, tmp_path
) -> None:
    secured_settings = ServingSettings(
        environment="test",
        startup_load_enabled=False,
        viz_data_dir=tmp_path / "viz",
        internal_api_key="super-secret-internal-key",
    )
    holder = ModelRegistryHolder(secured_settings)
    holder.set_predictor(trained_predictor, load_seconds=0.05)
    client = TestClient(create_app(settings=secured_settings, holder=holder))

    # Probes and /metrics MUST pass without X-Internal-Api-Key
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 200
    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code == 200
    assert client.get("/metrics").status_code == 200

    # Protected endpoints fail with 401 ErrorResponse when key is missing or wrong
    req_id = str(uuid4())
    unauth = client.get("/model-info", headers={"X-Request-ID": req_id})
    assert unauth.status_code == 401
    assert unauth.json()["code"] == "UNAUTHORIZED"
    assert unauth.json()["request_id"] == req_id
    assert unauth.headers["X-Request-ID"] == req_id

    wrong_key = client.get(
        "/model-info",
        headers={"X-Internal-Api-Key": "wrong-key", "X-Request-ID": req_id},
    )
    assert wrong_key.status_code == 401
    assert wrong_key.json()["code"] == "UNAUTHORIZED"

    # Protected endpoint succeeds when valid X-Internal-Api-Key is supplied
    ok_resp = client.get(
        "/model-info",
        headers={"X-Internal-Api-Key": "super-secret-internal-key"},
    )
    assert ok_resp.status_code == 200


# ---------------------------------------------------------------------------
# 4. Strict Validation: NaN/Inf, Extra Fields, Bad Enums, Negatives, Schema Version, Zero Amount
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("bad_payload", "expected_code"),
    [
        # Negative amount
        (
            {
                "schema_version": "1.0",
                "request_id": "550e8400-e29b-41d4-a716-446655440000",
                "features": {
                    "type": "TRANSFER",
                    "amount": -10.0,
                    "sender_old_balance": 100.0,
                    "sender_new_balance": 110.0,
                    "receiver_old_balance": 0.0,
                    "receiver_new_balance": 0.0,
                },
            },
            "VALIDATION_FAILED",
        ),
        # Negative balance
        (
            {
                "schema_version": "1.0",
                "request_id": "550e8400-e29b-41d4-a716-446655440000",
                "features": {
                    "type": "TRANSFER",
                    "amount": 10.0,
                    "sender_old_balance": -1.0,
                    "sender_new_balance": 0.0,
                    "receiver_old_balance": 0.0,
                    "receiver_new_balance": 10.0,
                },
            },
            "VALIDATION_FAILED",
        ),
        # Invalid transaction type enum (including out-of-scope PaySim type PAYMENT)
        (
            {
                "schema_version": "1.0",
                "request_id": "550e8400-e29b-41d4-a716-446655440000",
                "features": {
                    "type": "PAYMENT",
                    "amount": 100.0,
                    "sender_old_balance": 100.0,
                    "sender_new_balance": 0.0,
                    "receiver_old_balance": 0.0,
                    "receiver_new_balance": 100.0,
                },
            },
            "VALIDATION_FAILED",
        ),
        # Missing required feature field
        (
            {
                "schema_version": "1.0",
                "request_id": "550e8400-e29b-41d4-a716-446655440000",
                "features": {
                    "type": "TRANSFER",
                    "amount": 100.0,
                },
            },
            "VALIDATION_FAILED",
        ),
        # Unknown extra field on features (extra="forbid")
        (
            {
                "schema_version": "1.0",
                "request_id": "550e8400-e29b-41d4-a716-446655440000",
                "features": {
                    "type": "TRANSFER",
                    "amount": 100.0,
                    "sender_old_balance": 100.0,
                    "sender_new_balance": 0.0,
                    "receiver_old_balance": 0.0,
                    "receiver_new_balance": 100.0,
                    "isFlaggedFraud": 1,
                },
            },
            "VALIDATION_FAILED",
        ),
        # Unsupported schema_version -> dedicated UNSUPPORTED_SCHEMA_VERSION code
        (
            {
                "schema_version": "2.0",
                "request_id": "550e8400-e29b-41d4-a716-446655440000",
                "features": {
                    "type": "TRANSFER",
                    "amount": 100.0,
                    "sender_old_balance": 100.0,
                    "sender_new_balance": 0.0,
                    "receiver_old_balance": 0.0,
                    "receiver_new_balance": 100.0,
                },
            },
            "UNSUPPORTED_SCHEMA_VERSION",
        ),
    ],
)
def test_predict_strict_validation_errors(
    test_settings: ServingSettings,
    loaded_holder: ModelRegistryHolder,
    bad_payload: dict,
    expected_code: str,
) -> None:
    client = TestClient(create_app(settings=test_settings, holder=loaded_holder))
    resp = client.post("/predict", json=bad_payload)
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == expected_code
    assert body["status"] == 422
    assert body["request_id"] == "550e8400-e29b-41d4-a716-446655440000"
    assert len(body["detail"]) >= 1


def test_predict_rejects_nan_and_infinity(
    test_settings: ServingSettings, loaded_holder: ModelRegistryHolder
) -> None:
    # Pydantic schema level check for float('nan') and float('inf')
    with pytest.raises(ValidationError):
        TransactionFeatures(
            type=TransactionType.TRANSFER,
            amount=float("nan"),
            sender_old_balance=100.0,
            sender_new_balance=100.0,
            receiver_old_balance=0.0,
            receiver_new_balance=0.0,
        )
    with pytest.raises(ValidationError):
        TransactionFeatures(
            type=TransactionType.TRANSFER,
            amount=float("inf"),
            sender_old_balance=100.0,
            sender_new_balance=100.0,
            receiver_old_balance=0.0,
            receiver_new_balance=0.0,
        )


def test_predict_zero_amount_accepted_for_paysim_parity(
    test_settings: ServingSettings, loaded_holder: ModelRegistryHolder
) -> None:
    client = TestClient(create_app(settings=test_settings, holder=loaded_holder))
    req_id = str(uuid4())
    resp = client.post(
        "/predict",
        json={
            "schema_version": "1.0",
            "request_id": req_id,
            "features": {
                "type": "CASH_OUT",
                "amount": 0.0,
                "sender_old_balance": 0.0,
                "sender_new_balance": 0.0,
                "receiver_old_balance": 500.0,
                "receiver_new_balance": 500.0,
            },
        },
    )
    assert resp.status_code == 200
    assert resp.json()["request_id"] == req_id


# ---------------------------------------------------------------------------
# 5. Visualization Endpoint (/viz/{method}) & Point Cap (2,000 points)
# ---------------------------------------------------------------------------
def test_viz_endpoint_404_when_missing_and_caps_at_2000_points(
    test_settings: ServingSettings, loaded_holder: ModelRegistryHolder
) -> None:
    client = TestClient(create_app(settings=test_settings, holder=loaded_holder))

    # Missing file -> 404 ErrorResponse
    missing_resp = client.get("/viz/pca")
    assert missing_resp.status_code == 404
    assert missing_resp.json()["code"] == "NOT_FOUND"

    # Write 2,500 points into pca.json and verify response caps at 2,000
    points = [
        {
            "x": float(i) * 0.01,
            "y": float(i) * -0.01,
            "true_label": i % 2,
            "predicted_label": i % 2,
            "uncertain": False,
            "error": False,
            "type": "TRANSFER",
            "amount": 1000.0,
            "balance_drain_ratio": 0.5,
        }
        for i in range(2500)
    ]
    pca_file = test_settings.viz_data_dir / "pca.json"
    pca_file.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "method": "pca",
                "n_points": len(points),
                "generated_at": "2026-10-26T12:00:00Z",
                "points": points,
            }
        ),
        encoding="utf-8",
    )

    ok_resp = client.get("/viz/pca")
    assert ok_resp.status_code == 200
    data = ok_resp.json()
    assert data["method"] == "pca"
    assert data["n_points"] == 2000
    assert len(data["points"]) == 2000


# ---------------------------------------------------------------------------
# 6. Prometheus Metrics & Route Template Labels
# ---------------------------------------------------------------------------
def test_prometheus_metrics_increment_with_route_templates_and_finite_reasons(
    test_settings: ServingSettings, loaded_holder: ModelRegistryHolder
) -> None:
    client = TestClient(create_app(settings=test_settings, holder=loaded_holder))

    client.get("/viz/umap")
    client.post(
        "/predict",
        json={
            "schema_version": "1.0",
            "request_id": str(uuid4()),
            "features": {
                "type": "TRANSFER",
                "amount": 250000.0,
                "sender_old_balance": 250000.0,
                "sender_new_balance": 0.0,
                "receiver_old_balance": 0.0,
                "receiver_new_balance": 250000.0,
            },
        },
    )

    metrics_text = client.get("/metrics").text
    assert "ml_ready 1.0" in metrics_text
    assert 'ml_model_info{alias="production",model_name="fraud-detector",stage="Production",version="3"} 1.0' in metrics_text
    assert 'ml_predictions_total{action="BLOCK",model_version="3",prediction_set="fraud"}' in metrics_text
    # Route template `/viz/{method}` must appear, NEVER raw `/viz/umap`
    assert 'route="/viz/{method}"' in metrics_text
    assert 'route="/viz/umap"' not in metrics_text


# ---------------------------------------------------------------------------
# 7. Direct Predictor Latency Benchmark (p95 < 300ms)
# ---------------------------------------------------------------------------
def test_direct_predictor_p95_latency_under_budget(
    trained_predictor: TrainedModelPredictor,
) -> None:
    request = PredictRequest(
        schema_version="1.0",
        request_id=uuid4(),
        features=TransactionFeatures(
            type=TransactionType.TRANSFER,
            amount=1250.5,
            sender_old_balance=5000.0,
            sender_new_balance=3749.5,
            receiver_old_balance=100.0,
            receiver_new_balance=1350.5,
        ),
    )
    # Warmup call
    trained_predictor.predict(request)

    latencies_ms: list[float] = []
    for _ in range(100):
        t0 = time.perf_counter_ns()
        trained_predictor.predict(request)
        latencies_ms.append((time.perf_counter_ns() - t0) / 1_000_000.0)

    p95_ms = float(np.percentile(latencies_ms, 95))
    assert p95_ms < 300.0, f"Predictor p95 latency {p95_ms:.2f}ms exceeded 300ms budget"
