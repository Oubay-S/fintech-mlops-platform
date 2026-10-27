"""Shared MLflow artifact contract for the fraud model (Roles 4 and 5).

Implementation referenced by ``mlflow-artifact-contract.md``. It defines:

- the canonical experiment/model/alias names;
- the ``uncertainty_config.json`` schema;
- the Mondrian/split-conformal prediction-set rule used at serving;
- an MLflow logging helper that logs the pipeline and the config in one run.

The registered sklearn pipeline is **not** end-to-end from the raw six fields:
the serving layer must call
``ml.common.preprocessing.build_serving_features(raw_frame)`` before
``pipeline.predict_proba(...)``. ``build_features`` is the PaySim-column
training counterpart; both produce the same 10-column frame.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .schema import CONTRACT_FEATURES, DERIVED_FEATURES

MODEL_NAME = "fraud-detector"
EXPERIMENT_NAME = "paysim-fraud-benchmark"
PRODUCTION_ALIAS = "production"
STAGING_ALIAS = "staging"
UNCERTAINTY_CONFIG_FILENAME = "uncertainty_config.json"
ARTIFACT_SCHEMA_VERSION = "1.0"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class UncertaintyConfig:
    """Companion artifact logged next to the MLflow sklearn model."""

    confidence_level: float
    q_hat_fraud: float
    q_hat_legit: float
    target_review_rate: float = 0.05
    method: str = "mondrian_conformal"
    schema_version: str = ARTIFACT_SCHEMA_VERSION
    contract_features: list[str] = field(default_factory=lambda: list(CONTRACT_FEATURES))
    derived_features: list[str] = field(default_factory=lambda: list(DERIVED_FEATURES))
    model_feature_names: list[str] = field(default_factory=list)
    algorithm: str = "unknown"
    trained_at: str = field(default_factory=_utc_now)
    metrics_summary: dict[str, Any] = field(default_factory=dict)
    dataset_version: str = "paysim"
    feature_list_version: str = "1.1"
    eval_population: str = "app-valid TRANSFER+CASH_OUT"
    calibration_rows: int = 0
    calibration_frauds: int = 0

    def validate(self) -> None:
        if not 0.5 < self.confidence_level < 1.0:
            raise ValueError("confidence_level must be in (0.5, 1)")
        if not 0.0 < self.target_review_rate < 1.0:
            raise ValueError("target_review_rate must be in (0, 1)")
        for name in ("q_hat_fraud", "q_hat_legit"):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be in [0, 1]")
        if not self.contract_features:
            raise ValueError("contract_features must not be empty")
        if not self.derived_features:
            raise ValueError("derived_features must not be empty")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UncertaintyConfig":
        known = {f.name for f in cls.__dataclass_fields__.values()}
        config = cls(**{k: v for k, v in data.items() if k in known})
        config.validate()
        return config

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.write_text(json.dumps(self.to_dict(), indent=2))
        return path

    @classmethod
    def load(cls, path: str | Path) -> "UncertaintyConfig":
        return cls.from_dict(json.loads(Path(path).read_text()))


def prediction_set(p_fraud: float, config: UncertaintyConfig) -> list[str]:
    """Mondrian/split-conformal prediction set for one fraud probability.

    ``legit`` is included iff ``p_fraud <= q_hat_legit``.
    ``fraud`` is included iff ``1 - p_fraud <= q_hat_fraud``.
    The empty set and the both-class set are valid.
    """
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
    artifact_path: str = "model",
    registered_model_name: str = MODEL_NAME,
    signature=None,
    input_example=None,
):
    """Log the fitted sklearn pipeline and ``uncertainty_config.json`` in one run.

    The caller owns the MLflow run/experiment. ``mlflow`` is imported lazily so
    training and tests do not require it.
    """
    import mlflow
    import mlflow.sklearn

    mlflow.sklearn.log_model(
        sk_model=pipeline,
        artifact_path=artifact_path,
        registered_model_name=registered_model_name,
        signature=signature,
        input_example=input_example,
    )
    mlflow.log_dict(config.to_dict(), UNCERTAINTY_CONFIG_FILENAME)
