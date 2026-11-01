"""MLflow Model Registry & Artifact Contract shared between ML Training (Role 4) and ML Serving (Role 5).

This module defines the single canonical contract for:
1. Experiment naming and required run tags.
2. Required logged evaluation metrics.
3. Artifact layout inside an MLflow run (`model/` + `uncertainty_config.json`).
4. Expected 14-column transformed feature signature after `build_preprocessor()`.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

from .schema import (
    CONTRACT_FEATURES,
    DERIVED_FEATURES,
    NUMERIC_FEATURES,
    TRANSACTION_TYPES,
)

# ---------------------------------------------------------------------------
# 1. MLflow Registry & Experiment Naming Contract
# ---------------------------------------------------------------------------
DEFAULT_EXPERIMENT_NAME = "paysim-fraud-benchmark"
EXPERIMENT_NAME = DEFAULT_EXPERIMENT_NAME
REGISTERED_MODEL_NAME = "fraud-detector"
MODEL_NAME = REGISTERED_MODEL_NAME

CANDIDATE_ALIAS = "candidate"
STAGING_ALIAS = "staging"
PRODUCTION_ALIAS = "production"
PREVIOUS_ALIAS = "previous"

# Artifacts expected inside every registered MLflow model run
MODEL_ARTIFACT_PATH = "model"
UNCERTAINTY_CONFIG_ARTIFACT = "uncertainty_config.json"
STATISTICAL_VALIDATION_ARTIFACT = "statistical_validation.json"
UNCERTAINTY_SHA256_TAG = "uncertainty_config_sha256"
DATA_SOURCE_TAG = "data_source"

# Expected 14 transformed feature names out of `build_preprocessor()` (9 numeric + 5 one-hot)
EXPECTED_TRANSFORMED_FEATURES: list[str] = list(NUMERIC_FEATURES) + [
    f"type_{t}" for t in TRANSACTION_TYPES
]

# Required metrics logged on the in-scope (TRANSFER + CASH_OUT) evaluation split
REQUIRED_LOGGED_METRICS: tuple[str, ...] = (
    "roc_auc",
    "pr_auc",
    "f1",
    "precision",
    "recall",
    "mcc",
    "brier_score",
    "expected_review_rate",
    "inference_p95_ms",
)

REQUIRED_RUN_TAGS: tuple[str, ...] = (
    "algorithm",
    "dataset_version",
    "git_sha",
    "seed",
)


@dataclass(frozen=True)
class UncertaintyConfigContract:
    """Schema for `uncertainty_config.json` logged alongside the sklearn pipeline in MLflow.

    In Mondrian / split conformal prediction:
    - Non-conformity score for class `y` is `s_y(x) = 1 - P(Y = y | x)`.
    - Class `"fraud"` is included in `prediction_set` iff `1 - p_fraud <= q_hat_fraud`
      (equivalently, `p_fraud >= 1 - q_hat_fraud`).
    - Class `"legit"` is included in `prediction_set` iff `p_fraud <= q_hat_legit`
      (since `1 - p_legit = p_fraud`).
    """

    method: str = "split_conformal"
    confidence_level: float = 0.95
    target_review_rate: float = 0.05
    q_hat_fraud: float = 0.60
    q_hat_legit: float = 0.85
    high_uncertainty_score_threshold: float = 0.50
    algorithm: str = "LogisticRegression"
    trained_at: str = "2026-10-26T00:00:00Z"
    feature_names: list[str] = field(
        default_factory=lambda: list(CONTRACT_FEATURES + DERIVED_FEATURES)
    )
    transformed_feature_names: list[str] = field(
        default_factory=lambda: list(EXPECTED_TRANSFORMED_FEATURES)
    )
    metrics_summary: dict[str, float] = field(
        default_factory=lambda: {
            "roc_auc": 0.9990,
            "pr_auc": 0.9976,
            "f1": 0.9960,
            "precision": 1.0000,
            "recall": 0.9921,
            "mcc": 0.9960,
            "brier_score": 0.000007,
            "expected_review_rate": 0.0180,
            "inference_p95_ms": 4.2,
        }
    )

    def validate(self) -> None:
        """Validate conformal configuration invariants."""
        if self.method not in (
            "split_conformal",
            "mondrian_conformal",
            "ensemble_bootstrap",
        ):
            raise ValueError(f"Unsupported uncertainty method: {self.method}")
        if not (0.5 <= self.confidence_level <= 0.999):
            raise ValueError(
                f"confidence_level out of range [0.5, 0.999]: {self.confidence_level}"
            )
        if not (0.0 < self.q_hat_fraud <= 1.0):
            raise ValueError(f"q_hat_fraud must be in (0, 1]: {self.q_hat_fraud}")
        if not (0.0 < self.q_hat_legit <= 1.0):
            raise ValueError(f"q_hat_legit must be in (0, 1]: {self.q_hat_legit}")
        expected_input = list(CONTRACT_FEATURES + DERIVED_FEATURES)
        if list(self.feature_names) != expected_input:
            raise ValueError(
                f"Feature signature mismatch: model expects {self.feature_names}, "
                f"serving pipeline produces {expected_input}"
            )
        if list(self.transformed_feature_names) != list(EXPECTED_TRANSFORMED_FEATURES):
            raise ValueError(
                f"Transformed feature signature mismatch: model expects {self.transformed_feature_names}, "
                f"serving pipeline produces {EXPECTED_TRANSFORMED_FEATURES}"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def sha256(self) -> str:
        """Compute canonical SHA-256 hex digest of this uncertainty configuration."""
        return compute_uncertainty_sha256(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UncertaintyConfigContract:
        transformed = data.get("transformed_feature_names") or data.get(
            "model_feature_names"
        )
        raw_metrics = data.get("metrics_summary", {})
        clean_metrics = {
            str(k): float(v)
            for k, v in raw_metrics.items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)
        }
        cfg = cls(
            method=str(data.get("method", "split_conformal")),
            confidence_level=float(data.get("confidence_level", 0.95)),
            target_review_rate=float(data.get("target_review_rate", 0.05)),
            q_hat_fraud=float(data.get("q_hat_fraud", 0.60)),
            q_hat_legit=float(data.get("q_hat_legit", 0.85)),
            high_uncertainty_score_threshold=float(
                data.get("high_uncertainty_score_threshold", 0.50)
            ),
            algorithm=str(data.get("algorithm", "UnknownClassifier")),
            trained_at=str(data.get("trained_at", "2026-10-26T00:00:00Z")),
            feature_names=list(
                data.get("feature_names", CONTRACT_FEATURES + DERIVED_FEATURES)
            ),
            transformed_feature_names=list(
                transformed
                if transformed is not None
                else EXPECTED_TRANSFORMED_FEATURES
            ),
            metrics_summary=clean_metrics,
        )
        cfg.validate()
        return cfg


# Alias for Role 4 training compatibility
UncertaintyConfig = UncertaintyConfigContract


def compute_uncertainty_sha256(
    config: UncertaintyConfigContract | dict[str, Any],
) -> str:
    """Compute deterministic SHA-256 hex digest over the canonical uncertainty config."""
    if isinstance(config, UncertaintyConfigContract):
        payload = config.to_dict()
    else:
        payload = UncertaintyConfigContract.from_dict(config).to_dict()
    canonical_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(canonical_bytes).hexdigest()


def verify_uncertainty_sha256(
    *,
    expected_sha256: str,
    config: UncertaintyConfigContract,
    raw_bytes: bytes | None = None,
    raw_dict: dict[str, Any] | None = None,
) -> bool:
    """Verify an uncertainty config against its recorded SHA-256 tag.

    Accepts a match against:
    1. The canonical `UncertaintyConfigContract` SHA-256 (`compute_uncertainty_sha256(config)`).
    2. The sorted-keys JSON digest of `raw_dict` (if training included extra metadata keys).
    3. The exact `raw_bytes` file digest (if computed directly on file bytes).
    """
    expected = expected_sha256.strip().lower()
    if not expected:
        return False
    if compute_uncertainty_sha256(config).lower() == expected:
        return True
    if raw_dict is not None:
        raw_canonical = json.dumps(
            raw_dict, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        if hashlib.sha256(raw_canonical).hexdigest().lower() == expected:
            return True
    return bool(
        raw_bytes is not None
        and hashlib.sha256(raw_bytes).hexdigest().lower() == expected
    )
