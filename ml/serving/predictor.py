"""Strict ML-only Predictor interface and conformal prediction wrapper.

Rules enforced:
1. Zero heuristic fallback: Only trained ML models loaded from MLflow are served.
2. Zero training-serving skew: Calls `ml.common.preprocessing.build_features` directly.
3. Validates that the model's expected feature signature matches `FEATURE_COLUMNS`.
"""
from __future__ import annotations

import math
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np
import pandas as pd

from ml.common.artifact_contract import UncertaintyConfigContract
from ml.common.preprocessing import build_features
from ml.common.schema import CONTRACT_FEATURES, DERIVED_FEATURES, FEATURE_COLUMNS

from .schemas import (
    ConformalConfigMetadata,
    FeatureExplanation,
    MetricsSummaryMetadata,
    ModelAlias,
    ModelDetailMetadata,
    ModelInfoResponse,
    ModelRef,
    ModelStage,
    PredictionLabel,
    PredictRequest,
    PredictResponse,
    SuggestedAction,
    TransactionFeatures,
    UncertaintyEstimate,
    UncertaintyMethod,
)


class ModelNotReadyError(RuntimeError):
    """Raised when `/predict`, `/model-info`, or `/health/ready` is called before a trained model is loaded."""


class SupportsPredictProba(Protocol):
    """Protocol for trained scikit-learn pipelines / estimators supporting `predict_proba`."""

    def predict_proba(self, X: pd.DataFrame | np.ndarray) -> np.ndarray:
        ...


@dataclass(frozen=True)
class PredictionOutcome:
    """Internal result combining the API response and finite Prometheus metric labels."""

    response: PredictResponse
    review_reason: str | None  # Finite values: "ambiguous_set", "empty_set", "high_score", or None


class Predictor(ABC):
    """Abstract interface for transaction fraud scoring."""

    @abstractmethod
    def predict(self, request: PredictRequest) -> PredictionOutcome:
        """Score a single transaction synchronously."""

    @abstractmethod
    def get_model_ref(self) -> ModelRef:
        """Return lightweight model reference for `/predict` and `/health/ready`."""

    @abstractmethod
    def get_model_info(self) -> ModelInfoResponse:
        """Return full model metadata, conformal config, and validation metrics for `/model-info`."""


class TrainedModelPredictor(Predictor):
    """Production predictor wrapping a trained sklearn Pipeline + Conformal `UncertaintyConfigContract`."""

    def __init__(
        self,
        *,
        model: SupportsPredictProba,
        uncertainty_config: UncertaintyConfigContract,
        model_name: str,
        model_version: str,
        model_alias: str = "production",
        run_id: str | None = None,
    ) -> None:
        uncertainty_config.validate()
        if list(uncertainty_config.feature_names) != list(FEATURE_COLUMNS):
            raise ValueError(
                f"Model feature signature {uncertainty_config.feature_names} "
                f"does not match FEATURE_COLUMNS {FEATURE_COLUMNS}"
            )

        self._model = model
        self._config = uncertainty_config
        self._model_name = model_name
        self._model_version = str(model_version)
        alias_norm = model_alias.strip().lower()
        self._model_alias = (
            ModelAlias.STAGING if alias_norm == "staging" else ModelAlias.PRODUCTION
        )
        self._model_stage = (
            ModelStage.STAGING
            if self._model_alias == ModelAlias.STAGING
            else ModelStage.PRODUCTION
        )
        self._run_id = run_id

    @staticmethod
    def features_to_dataframe(features: TransactionFeatures) -> pd.DataFrame:
        """Convert validated `TransactionFeatures` into the exact 10-column DataFrame via `build_features`."""
        single_row = pd.DataFrame(
            [
                {
                    "type": features.type.value,
                    "amount": float(features.amount),
                    "sender_old_balance": float(features.sender_old_balance),
                    "sender_new_balance": float(features.sender_new_balance),
                    "receiver_old_balance": float(features.receiver_old_balance),
                    "receiver_new_balance": float(features.receiver_new_balance),
                }
            ]
        )
        engineered = build_features(single_row)
        return engineered[list(FEATURE_COLUMNS)]

    def _compute_conformal_set(
        self, fraud_prob: float
    ) -> tuple[list[PredictionLabel], float, SuggestedAction, str | None]:
        """Compute Mondrian / split-conformal prediction set and scalar uncertainty score."""
        p_fraud = float(np.clip(fraud_prob, 0.0, 1.0))

        # Non-conformity scores:
        # s_legit(x) = 1 - P(Y=0|x) = p_fraud
        # s_fraud(x) = 1 - P(Y=1|x) = 1 - p_fraud
        prediction_set: list[PredictionLabel] = []
        if p_fraud <= self._config.q_hat_legit:
            prediction_set.append(PredictionLabel.LEGIT)
        if (1.0 - p_fraud) <= self._config.q_hat_fraud:
            prediction_set.append(PredictionLabel.FRAUD)

        # Normalized binary Shannon entropy in [0, 1] as scalar uncertainty score
        eps = 1e-12
        p_clamped = min(max(p_fraud, eps), 1.0 - eps)
        entropy = -(
            p_clamped * math.log2(p_clamped)
            + (1.0 - p_clamped) * math.log2(1.0 - p_clamped)
        )
        uncertainty_score = float(np.clip(entropy, 0.0, 1.0))

        # Determine suggested action and finite Prometheus metric reason label
        review_reason: str | None = None
        if len(prediction_set) == 0:
            action = SuggestedAction.HUMAN_REVIEW
            review_reason = "empty_set"
            uncertainty_score = max(uncertainty_score, 0.85)
        elif len(prediction_set) == 2:
            action = SuggestedAction.HUMAN_REVIEW
            review_reason = "ambiguous_set"
        elif prediction_set[0] == PredictionLabel.FRAUD:
            action = SuggestedAction.BLOCK
        else:
            if uncertainty_score >= self._config.high_uncertainty_score_threshold:
                action = SuggestedAction.HUMAN_REVIEW
                review_reason = "high_score"
            else:
                action = SuggestedAction.ALLOW

        return prediction_set, round(uncertainty_score, 6), action, review_reason

    def _extract_fast_explanations(
        self, engineered_df: pd.DataFrame
    ) -> list[FeatureExplanation] | None:
        """Compute sub-millisecond linear feature attributions if the underlying pipeline exposes them."""
        try:
            named_steps: dict[str, Any] = getattr(self._model, "named_steps", {})
            preprocessor = named_steps.get("preprocessor")
            classifier = named_steps.get("classifier")
            if preprocessor is None or classifier is None:
                return None
            coef = getattr(classifier, "coef_", None)
            if coef is None:
                return None

            transformed = preprocessor.transform(engineered_df)
            feature_names = list(preprocessor.get_feature_names_out())
            weights = np.asarray(coef[0], dtype=float)
            values = np.asarray(transformed[0], dtype=float)
            contribs = weights * values

            top_indices = np.argsort(np.abs(contribs))[::-1][:3]
            return [
                FeatureExplanation(
                    feature=str(feature_names[idx]).removeprefix("num__").removeprefix("cat__"),
                    contribution=round(float(contribs[idx]), 4),
                )
                for idx in top_indices
            ]
        except Exception:  # noqa: BLE001
            return None

    def predict(self, request: PredictRequest) -> PredictionOutcome:
        start_ns = time.perf_counter_ns()

        engineered_df = self.features_to_dataframe(request.features)
        proba_matrix = np.asarray(self._model.predict_proba(engineered_df), dtype=float)
        if proba_matrix.ndim != 2 or proba_matrix.shape[1] < 2:
            raise ValueError(f"Expected 2-class probability array, got shape {proba_matrix.shape}")

        fraud_prob = float(np.clip(proba_matrix[0, 1], 0.0, 1.0))
        prediction_set, uncertainty_score, action, review_reason = self._compute_conformal_set(
            fraud_prob
        )
        explanations = self._extract_fast_explanations(engineered_df)

        elapsed_ms = (time.perf_counter_ns() - start_ns) / 1_000_000.0

        response = PredictResponse(
            schema_version="1.0",
            request_id=request.request_id,
            action=action,
            fraud_probability=round(fraud_prob, 6),
            uncertainty=UncertaintyEstimate(
                method=UncertaintyMethod(self._config.method),
                confidence_level=self._config.confidence_level,
                prediction_set=prediction_set,
                score=uncertainty_score,
            ),
            model=self.get_model_ref(),
            explanations=explanations,
            inference_ms=round(max(elapsed_ms, 0.01), 3),
        )
        return PredictionOutcome(response=response, review_reason=review_reason)

    def get_model_ref(self) -> ModelRef:
        return ModelRef(
            name=self._model_name,
            version=self._model_version,
            stage=self._model_stage,
            alias=self._model_alias,
        )

    def get_model_info(self) -> ModelInfoResponse:
        m = self._config.metrics_summary
        return ModelInfoResponse(
            schema_version="1.0",
            model=ModelDetailMetadata(
                name=self._model_name,
                version=self._model_version,
                stage=self._model_stage,
                alias=self._model_alias,
                algorithm=self._config.algorithm,
                run_id=self._run_id,
                trained_at=self._config.trained_at,
            ),
            conformal_config=ConformalConfigMetadata(
                method=UncertaintyMethod(self._config.method),
                confidence_level=self._config.confidence_level,
                target_review_rate=self._config.target_review_rate,
                q_hat_fraud=self._config.q_hat_fraud,
                q_hat_legit=self._config.q_hat_legit,
            ),
            metrics_summary=MetricsSummaryMetadata(
                roc_auc=m.get("roc_auc"),
                pr_auc=m.get("pr_auc"),
                f1=m.get("f1"),
                precision=m.get("precision"),
                recall=m.get("recall"),
                mcc=m.get("mcc"),
                brier_score=m.get("brier_score"),
                expected_review_rate=m.get("expected_review_rate"),
                inference_p95_ms=m.get("inference_p95_ms"),
            ),
            contract_features=list(CONTRACT_FEATURES),
            derived_features=list(DERIVED_FEATURES),
        )
