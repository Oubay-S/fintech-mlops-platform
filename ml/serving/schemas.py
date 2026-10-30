"""Pydantic v2 request and response schemas for the FastAPI ML Serving microservice.

Strictly enforces:
- `extra="forbid"` on request payloads (`PredictRequest`, `TransactionFeatures`).
- `allow_inf_nan=False` on all numeric fields (rejects `NaN`, `Infinity`, `-Infinity`).
- `amount >= 0.0` (supports the 16 PaySim zero-amount fraud rows for parity tests).
- `schema_version` validation (`^1\\.[0-9]+$`) with dedicated error code `UNSUPPORTED_SCHEMA_VERSION`.
"""
from __future__ import annotations

import re
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA_VERSION_REGEX = re.compile(r"^1\.[0-9]+$")


class UnsupportedSchemaVersionError(ValueError):
    """Raised when `schema_version` is not a supported 1.x version."""


class TransactionType(str, Enum):
    """In-scope PaySim transaction types supported by the application and ML model."""

    TRANSFER = "TRANSFER"
    CASH_OUT = "CASH_OUT"


class PredictionLabel(str, Enum):
    """Conformal prediction set class labels."""

    LEGIT = "legit"
    FRAUD = "fraud"


class SuggestedAction(str, Enum):
    """Advisory action suggested by ML Serving."""

    ALLOW = "ALLOW"
    BLOCK = "BLOCK"
    HUMAN_REVIEW = "HUMAN_REVIEW"


class UncertaintyMethod(str, Enum):
    """Supported uncertainty quantification methods."""

    SPLIT_CONFORMAL = "split_conformal"
    MONDRIAN_CONFORMAL = "mondrian_conformal"
    ENSEMBLE_BOOTSTRAP = "ensemble_bootstrap"


class ModelStage(str, Enum):
    """MLflow model lifecycle stages required by Section 17.2."""

    PRODUCTION = "Production"
    STAGING = "Staging"


class ModelAlias(str, Enum):
    """MLflow 2.x model aliases."""

    PRODUCTION = "production"
    STAGING = "staging"


class VizMethod(str, Enum):
    """Supported 2D dimensionality reduction methods."""

    PCA = "pca"
    TSNE = "tsne"
    UMAP = "umap"


class ErrorCode(str, Enum):
    """Canonical error codes returned in `ErrorResponse.code`."""

    VALIDATION_FAILED = "VALIDATION_FAILED"
    UNSUPPORTED_SCHEMA_VERSION = "UNSUPPORTED_SCHEMA_VERSION"
    MODEL_NOT_READY = "MODEL_NOT_READY"
    UNAUTHORIZED = "UNAUTHORIZED"
    NOT_FOUND = "NOT_FOUND"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class TransactionFeatures(BaseModel):
    """The 6 PaySim contract features sent by `risk-service` at decision time."""

    model_config = ConfigDict(extra="forbid")

    type: TransactionType
    amount: float = Field(
        ...,
        ge=0.0,
        allow_inf_nan=False,
        description="Transaction amount (>= 0.0 to support PaySim zero-amount fraud rows in parity tests)",
    )
    sender_old_balance: float = Field(
        ...,
        ge=0.0,
        allow_inf_nan=False,
        description="Sender wallet balance before the transaction (oldbalanceOrg in PaySim)",
    )
    sender_new_balance: float = Field(
        ...,
        ge=0.0,
        allow_inf_nan=False,
        description="Expected sender wallet balance after the transaction (newbalanceOrig in PaySim)",
    )
    receiver_old_balance: float = Field(
        ...,
        ge=0.0,
        allow_inf_nan=False,
        description="Receiver wallet balance before the transaction (oldbalanceDest in PaySim)",
    )
    receiver_new_balance: float = Field(
        ...,
        ge=0.0,
        allow_inf_nan=False,
        description="Expected receiver wallet balance after the transaction (newbalanceDest in PaySim)",
    )


class PredictRequest(BaseModel):
    """Request payload for `POST /predict`."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(
        ...,
        description="Contract schema version (1.x required by Risk Service)",
    )
    request_id: UUID = Field(
        ...,
        description="Unique identifier for the scoring request",
    )
    features: TransactionFeatures

    @field_validator("schema_version")
    @classmethod
    def validate_schema_version(cls, value: str) -> str:
        if not isinstance(value, str) or not SCHEMA_VERSION_REGEX.match(value):
            raise UnsupportedSchemaVersionError(
                f"Unsupported schema_version '{value}'. Expected pattern '^1\\.[0-9]+$'."
            )
        return value


class UncertaintyEstimate(BaseModel):
    """Conformal prediction set and scalar uncertainty score."""

    model_config = ConfigDict(extra="forbid")

    method: UncertaintyMethod
    confidence_level: float = Field(
        ...,
        ge=0.5,
        le=0.999,
        allow_inf_nan=False,
        description="Target conformal coverage level (1 - alpha)",
    )
    prediction_set: list[PredictionLabel] = Field(
        ...,
        min_length=0,
        max_length=2,
        description="Conformal prediction set subset of {'legit', 'fraud'}",
    )
    score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        allow_inf_nan=False,
        description="Normalized scalar uncertainty score in [0, 1]",
    )


class ModelRef(BaseModel):
    """Registered model reference returned in `/predict` and `/health/ready`."""

    model_config = ConfigDict(extra="forbid")

    name: str
    version: str
    stage: ModelStage
    alias: ModelAlias = ModelAlias.PRODUCTION


class FeatureExplanation(BaseModel):
    """Signed feature attribution weight toward the fraud class."""

    model_config = ConfigDict(extra="forbid")

    feature: str
    contribution: float = Field(..., allow_inf_nan=False)


class PredictResponse(BaseModel):
    """Response payload for `POST /predict`."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str
    request_id: UUID
    action: SuggestedAction
    fraud_probability: float = Field(..., ge=0.0, le=1.0, allow_inf_nan=False)
    uncertainty: UncertaintyEstimate
    model: ModelRef
    explanations: list[FeatureExplanation] | None = None
    inference_ms: float = Field(..., ge=0.0, allow_inf_nan=False)


class HealthLiveResponse(BaseModel):
    """Response payload for `GET /health/live` (and deprecated alias `GET /health`)."""

    status: str
    service: str
    model_version: str | None = None


class HealthReadyResponse(BaseModel):
    """Response payload for `GET /health/ready` when model is loaded (`200 OK`)."""

    status: str
    ready: bool
    model: ModelRef


class ModelDetailMetadata(BaseModel):
    """Detailed model metadata inside `ModelInfoResponse`."""

    name: str
    version: str
    stage: ModelStage
    alias: ModelAlias
    algorithm: str
    run_id: str | None = None
    trained_at: str | None = None


class ConformalConfigMetadata(BaseModel):
    """Conformal calibration configuration inside `ModelInfoResponse`."""

    method: UncertaintyMethod
    confidence_level: float = Field(..., ge=0.5, le=0.999, allow_inf_nan=False)
    target_review_rate: float = Field(..., ge=0.0, le=1.0, allow_inf_nan=False)
    q_hat_fraud: float | None = Field(default=None, allow_inf_nan=False)
    q_hat_legit: float | None = Field(default=None, allow_inf_nan=False)


class MetricsSummaryMetadata(BaseModel):
    """Validation metrics recorded on the in-scope (`TRANSFER` + `CASH_OUT`) test split."""

    roc_auc: float | None = Field(default=None, allow_inf_nan=False)
    pr_auc: float | None = Field(default=None, allow_inf_nan=False)
    f1: float | None = Field(default=None, allow_inf_nan=False)
    precision: float | None = Field(default=None, allow_inf_nan=False)
    recall: float | None = Field(default=None, allow_inf_nan=False)
    mcc: float | None = Field(default=None, allow_inf_nan=False)
    brier_score: float | None = Field(default=None, allow_inf_nan=False)
    expected_review_rate: float | None = Field(default=None, allow_inf_nan=False)
    inference_p95_ms: float | None = Field(default=None, allow_inf_nan=False)


class ModelInfoResponse(BaseModel):
    """Response payload for `GET /model-info`."""

    schema_version: str
    model: ModelDetailMetadata
    conformal_config: ConformalConfigMetadata
    metrics_summary: MetricsSummaryMetadata
    contract_features: list[str]
    derived_features: list[str]


class EmbeddingPoint(BaseModel):
    """Single 2D point in PCA / t-SNE / UMAP embedding visualization."""

    x: float = Field(..., allow_inf_nan=False)
    y: float = Field(..., allow_inf_nan=False)
    true_label: int = Field(..., ge=0, le=1)
    predicted_label: int = Field(..., ge=0, le=1)
    uncertain: bool
    error: bool = False
    type: TransactionType
    amount: float = Field(..., ge=0.0, allow_inf_nan=False)
    balance_drain_ratio: float | None = Field(default=None, allow_inf_nan=False)


class EmbeddingVizResponse(BaseModel):
    """Response payload for `GET /viz/{method}`."""

    schema_version: str
    method: VizMethod
    n_points: int = Field(..., ge=0, le=10000)
    generated_at: str | None = None
    points: list[EmbeddingPoint] = Field(..., max_length=10000)


class ValidationErrorItem(BaseModel):
    """Individual field validation error detail."""

    loc: list[str]
    msg: str
    type: str


class ErrorResponse(BaseModel):
    """Unified error contract returned for all HTTP errors (401, 404, 422, 500, 503)."""

    code: ErrorCode
    message: str
    request_id: UUID
    status: int = Field(..., description="HTTP status code (401, 404, 422, 500, 503)")
    detail: list[ValidationErrorItem]

    @classmethod
    def build(
        cls,
        *,
        code: ErrorCode,
        message: str,
        request_id: UUID,
        status: int,
        detail: list[dict[str, Any] | ValidationErrorItem] | None = None,
    ) -> ErrorResponse:
        items: list[ValidationErrorItem] = []
        for item in detail or []:
            if isinstance(item, ValidationErrorItem):
                items.append(item)
            else:
                loc_list = [str(part) for part in item.get("loc", [])]
                items.append(
                    ValidationErrorItem(
                        loc=loc_list,
                        msg=str(item.get("msg", "")),
                        type=str(item.get("type", "value_error")),
                    )
                )
        return cls(
            code=code,
            message=message,
            request_id=request_id,
            status=status,
            detail=items,
        )
