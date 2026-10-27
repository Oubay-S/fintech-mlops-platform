"""Prometheus metrics instrumentation for the FastAPI ML Serving microservice.

Guarantees:
1. HTTP metrics use the matched FastAPI route template (`/viz/{method}`, `/predict`)
   instead of the raw path to prevent high-cardinality label explosion.
2. `ml_human_review_requests_total` uses a strictly finite `reason` label set:
   `ambiguous_set`, `empty_set`, `high_score`.
3. `ml_model_info` clears stale label sets (`ml_model_info.clear()`) whenever a model is loaded.
"""
from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

from .predictor import PredictionOutcome
from .schemas import ModelRef

FINITE_REVIEW_REASONS = frozenset({"ambiguous_set", "empty_set", "high_score"})

# ---------------------------------------------------------------------------
# 1. HTTP Request Metrics (keyed by route template, never raw path)
# ---------------------------------------------------------------------------
ML_HTTP_REQUESTS_TOTAL = Counter(
    "ml_http_requests_total",
    "Total HTTP requests handled by the ML Serving service",
    labelnames=("method", "route", "status"),
)

ML_HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "ml_http_request_duration_seconds",
    "HTTP request duration in seconds by route template",
    labelnames=("method", "route"),
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.3, 0.5, 1.0, 2.5),
)

# ---------------------------------------------------------------------------
# 2. Readiness & Model Lifecycle Gauges
# ---------------------------------------------------------------------------
ML_READY = Gauge(
    "ml_ready",
    "1 if a trained ML model and uncertainty config are loaded in memory, 0 otherwise",
)
ML_READY.set(0.0)

ML_MODEL_LOAD_SECONDS = Gauge(
    "ml_model_load_seconds",
    "Duration in seconds of the most recent successful MLflow model load",
)

ML_MODEL_INFO = Gauge(
    "ml_model_info",
    "Active ML model metadata loaded from MLflow Model Registry",
    labelnames=("model_name", "version", "stage", "alias"),
)

# ---------------------------------------------------------------------------
# 3. Real-Time Inference & Conformal Uncertainty Metrics
# ---------------------------------------------------------------------------
ML_INFERENCE_DURATION_SECONDS = Histogram(
    "ml_inference_duration_seconds",
    "Model preprocessing and inference latency in seconds",
    labelnames=("model_version",),
    buckets=(0.0005, 0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.2, 0.3, 0.5, 1.0),
)

ML_PREDICTIONS_TOTAL = Counter(
    "ml_predictions_total",
    "Total fraud predictions served, partitioned by action, conformal set, and model version",
    labelnames=("action", "prediction_set", "model_version"),
)

ML_HUMAN_REVIEW_REQUESTS_TOTAL = Counter(
    "ml_human_review_requests_total",
    "Total predictions flagged for human review due to conformal uncertainty",
    labelnames=("model_version", "reason"),
)

ML_PREDICTION_SET_SIZE = Histogram(
    "ml_prediction_set_size",
    "Distribution of conformal prediction set sizes (0, 1, or 2)",
    labelnames=("model_version",),
    buckets=(0, 1, 2),
)

ML_UNCERTAINTY_SCORE = Histogram(
    "ml_uncertainty_score",
    "Distribution of scalar uncertainty scores in [0, 1]",
    labelnames=("model_version",),
    buckets=(0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
)


def record_model_loaded(model_ref: ModelRef, load_seconds: float) -> None:
    """Update readiness and model metadata gauges when a model is loaded."""
    ML_MODEL_INFO.clear()
    ML_MODEL_INFO.labels(
        model_name=model_ref.name,
        version=model_ref.version,
        stage=model_ref.stage.value,
        alias=model_ref.alias.value,
    ).set(1.0)
    ML_MODEL_LOAD_SECONDS.set(max(float(load_seconds), 0.0))
    ML_READY.set(1.0)


def record_model_unloaded() -> None:
    """Mark service as not ready and clear active model info labels."""
    ML_MODEL_INFO.clear()
    ML_READY.set(0.0)


def record_prediction_metrics(outcome: PredictionOutcome) -> None:
    """Record latency, conformal set size, uncertainty score, and human-review counters."""
    resp = outcome.response
    version = resp.model.version
    pred_set_labels = sorted(label.value for label in resp.uncertainty.prediction_set)
    pred_set_key = ",".join(pred_set_labels) if pred_set_labels else "empty"

    ML_INFERENCE_DURATION_SECONDS.labels(model_version=version).observe(
        resp.inference_ms / 1000.0
    )
    ML_PREDICTIONS_TOTAL.labels(
        action=resp.action.value,
        prediction_set=pred_set_key,
        model_version=version,
    ).inc()
    ML_PREDICTION_SET_SIZE.labels(model_version=version).observe(
        float(len(resp.uncertainty.prediction_set))
    )
    ML_UNCERTAINTY_SCORE.labels(model_version=version).observe(
        float(resp.uncertainty.score)
    )

    if outcome.review_reason is not None:
        safe_reason = (
            outcome.review_reason
            if outcome.review_reason in FINITE_REVIEW_REASONS
            else "ambiguous_set"
        )
        ML_HUMAN_REVIEW_REQUESTS_TOTAL.labels(
            model_version=version,
            reason=safe_reason,
        ).inc()
