"""Canonical MLflow artifact contract shared by ML Training and ML Serving.

This is the single module both sides import. It keeps the serving-side
``UncertaintyConfigContract`` API (feature_names / transformed_feature_names,
MODEL_ARTIFACT_PATH, ...) while retaining the training-side metadata fields
(dataset/feature-list version, calibration size, eval population) and the
``log_pipeline`` helper.

Training logs with::

    log_pipeline(pipeline, config, alias=CANDIDATE_ALIAS)

The MLOps gate (``validate_gate.py`` + ``promote_model.py``) promotes the
candidate to ``@staging``/``@production``. Serving loads
``models:/fraud-detector@production`` plus the companion
``uncertainty_config.json``.
"""
from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
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
DATA_SOURCE = "paysim"

MODEL_ARTIFACT_PATH = "model"
UNCERTAINTY_CONFIG_ARTIFACT = "uncertainty_config.json"
UNCERTAINTY_CONFIG_FILENAME = UNCERTAINTY_CONFIG_ARTIFACT
ARTIFACT_SCHEMA_VERSION = "1.0"

# 14 transformed columns out of build_preprocessor() — the serving golden
# signature. The OneHotEncoder is pinned to all five PaySim categories, even
# when training data only contains TRANSFER/CASH_OUT.
EXPECTED_TRANSFORMED_FEATURES: list[str] = list(NUMERIC_FEATURES) + [
    f"type_{transaction_type}" for transaction_type in TRANSACTION_TYPES
]

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
    "data_source",
    "git_sha",
    "seed",
    "uncertainty_config_sha256",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class UncertaintyConfig:
    """Schema for ``uncertainty_config.json`` (training + serving).

    Mondrian / split conformal:
    - ``legit`` is in the set iff ``p_fraud <= q_hat_legit``.
    - ``fraud`` is in the set iff ``1 - p_fraud <= q_hat_fraud``.
    """

    # Serving-facing fields
    method: str = "split_conformal"
    confidence_level: float = 0.95
    target_review_rate: float = 0.05
    q_hat_fraud: float = 0.60
    q_hat_legit: float = 0.85
    high_uncertainty_score_threshold: float = 0.50
    algorithm: str = "UnknownClassifier"
    trained_at: str = field(default_factory=_utc_now)
    feature_names: list[str] = field(
        default_factory=lambda: list(CONTRACT_FEATURES + DERIVED_FEATURES)
    )
    transformed_feature_names: list[str] = field(
        default_factory=lambda: list(EXPECTED_TRANSFORMED_FEATURES)
    )
    metrics_summary: dict[str, Any] = field(default_factory=dict)

    # Training-side metadata (ignored by the serving loader)
    schema_version: str = ARTIFACT_SCHEMA_VERSION
    contract_features: list[str] = field(default_factory=lambda: list(CONTRACT_FEATURES))
    derived_features: list[str] = field(default_factory=lambda: list(DERIVED_FEATURES))
    model_feature_names: list[str] = field(default_factory=list)
    dataset_version: str = "paysim"
    feature_list_version: str = "1.2"
    eval_population: str = "app-valid TRANSFER+CASH_OUT (serving-consistent)"
    calibration_rows: int = 0
    calibration_frauds: int = 0

    def __post_init__(self) -> None:
        if self.model_feature_names:
            self.transformed_feature_names = list(self.model_feature_names)
        else:
            self.model_feature_names = list(self.transformed_feature_names)
        if not self.feature_names:
            self.feature_names = list(self.contract_features) + list(self.derived_features)

    def validate(self) -> None:
        if self.method not in ("split_conformal", "mondrian_conformal", "ensemble_bootstrap"):
            raise ValueError(f"Unsupported uncertainty method: {self.method}")
        if not 0.5 <= self.confidence_level <= 0.999:
            raise ValueError(
                f"confidence_level out of range [0.5, 0.999]: {self.confidence_level}"
            )
        if not 0.0 < self.target_review_rate < 1.0:
            raise ValueError(
                f"target_review_rate must be in (0, 1): {self.target_review_rate}"
            )
        for name in ("q_hat_fraud", "q_hat_legit"):
            value = getattr(self, name)
            if not 0.0 < value <= 1.0:
                raise ValueError(f"{name} must be in (0, 1]: {value}")
        if not self.contract_features or not self.derived_features:
            raise ValueError("contract_features and derived_features must be non-empty")
        expected_input = list(CONTRACT_FEATURES + DERIVED_FEATURES)
        if list(self.feature_names) != expected_input:
            raise ValueError(
                f"Feature signature mismatch: model expects {self.feature_names}, "
                f"serving pipeline produces {expected_input}"
            )
        if list(self.transformed_feature_names) != list(EXPECTED_TRANSFORMED_FEATURES):
            raise ValueError(
                "Transformed feature signature mismatch: model expects "
                f"{self.transformed_feature_names}, serving pipeline produces "
                f"{EXPECTED_TRANSFORMED_FEATURES}"
            )

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UncertaintyConfig":
        def _metric(value: Any) -> Any:
            if value is None or isinstance(value, (bool, int, float)):
                return value
            return float(value)

        config = cls(
            method=str(data.get("method", "split_conformal")),
            confidence_level=float(data.get("confidence_level", 0.95)),
            target_review_rate=float(data.get("target_review_rate", 0.05)),
            q_hat_fraud=float(data.get("q_hat_fraud", 0.60)),
            q_hat_legit=float(data.get("q_hat_legit", 0.85)),
            high_uncertainty_score_threshold=float(
                data.get("high_uncertainty_score_threshold", 0.50)
            ),
            algorithm=str(data.get("algorithm", "UnknownClassifier")),
            trained_at=str(data.get("trained_at", _utc_now())),
            feature_names=list(
                data.get("feature_names", CONTRACT_FEATURES + DERIVED_FEATURES)
            ),
            transformed_feature_names=list(
                data.get("transformed_feature_names", EXPECTED_TRANSFORMED_FEATURES)
            ),
            metrics_summary={
                str(key): _metric(value)
                for key, value in data.get("metrics_summary", {}).items()
            },
            schema_version=str(data.get("schema_version", ARTIFACT_SCHEMA_VERSION)),
            contract_features=list(data.get("contract_features", CONTRACT_FEATURES)),
            derived_features=list(data.get("derived_features", DERIVED_FEATURES)),
            model_feature_names=list(data.get("model_feature_names", [])),
            dataset_version=str(data.get("dataset_version", "paysim")),
            feature_list_version=str(data.get("feature_list_version", "1.2")),
            eval_population=str(
                data.get(
                    "eval_population",
                    "app-valid TRANSFER+CASH_OUT (serving-consistent)",
                )
            ),
            calibration_rows=int(data.get("calibration_rows", 0)),
            calibration_frauds=int(data.get("calibration_frauds", 0)),
        )
        config.validate()
        return config

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.write_text(json.dumps(self.to_dict(), indent=2))
        return path

    @classmethod
    def load(cls, path: str | Path) -> "UncertaintyConfig":
        return cls.from_dict(json.loads(Path(path).read_text()))


# Serving-side canonical name
UncertaintyConfigContract = UncertaintyConfig


def prediction_set(p_fraud: float, config: UncertaintyConfig) -> list[str]:
    """Mondrian/split-conformal prediction set for one fraud probability."""
    if not 0.0 <= p_fraud <= 1.0:
        raise ValueError("p_fraud must be in [0, 1]")
    result: list[str] = []
    if p_fraud <= config.q_hat_legit:
        result.append("legit")
    if (1.0 - p_fraud) <= config.q_hat_fraud:
        result.append("fraud")
    return result


def suggested_action(labels: list[str]) -> str:
    """Advisory action; Risk owns the final R1–R6 policy."""
    if labels == ["fraud"]:
        return "BLOCK"
    if labels == ["legit"]:
        return "ALLOW"
    return "HUMAN_REVIEW"


def log_pipeline(
    pipeline,
    config: UncertaintyConfig,
    *,
    artifact_path: str = MODEL_ARTIFACT_PATH,
    registered_model_name: str = REGISTERED_MODEL_NAME,
    alias: str | None = None,
    signature=None,
    input_example=None,
    config_path: str | Path | None = None,
):
    """Log the fitted sklearn pipeline + ``uncertainty_config.json`` in one run.

    ``cloudpickle`` is forced so the ColumnTransformer survives the sklearn
    version boundary; the alias is promoted after registration when provided.
    When ``config_path`` is given, that exact file bytes are logged (so the
    caller can tag ``uncertainty_config_sha256`` atomically); otherwise the
    config is serialized with ``mlflow.log_dict``. The caller owns the MLflow
    run/experiment.
    """
    import mlflow
    import mlflow.sklearn
    from mlflow.tracking import MlflowClient

    kwargs = {
        "sk_model": pipeline,
        "artifact_path": artifact_path,
        "registered_model_name": registered_model_name,
        "signature": signature,
        "input_example": input_example,
    }
    try:
        model_info = mlflow.sklearn.log_model(
            serialization_format="cloudpickle", **kwargs
        )
    except TypeError:
        # Older MLflow without the serialization_format parameter.
        model_info = mlflow.sklearn.log_model(**kwargs)

    if config_path is not None:
        # Always log under the canonical name, regardless of the local path.
        with tempfile.TemporaryDirectory(prefix="mlflow_uncertainty_") as tmp_dir:
            canonical = Path(tmp_dir) / UNCERTAINTY_CONFIG_ARTIFACT
            shutil.copyfile(config_path, canonical)
            mlflow.log_artifact(str(canonical))
    else:
        mlflow.log_dict(config.to_dict(), UNCERTAINTY_CONFIG_ARTIFACT)

    version = getattr(model_info, "registered_model_version", None)
    if alias and version:
        MlflowClient().set_registered_model_alias(
            name=registered_model_name, alias=alias, version=str(version)
        )
    return model_info
