"""12-Factor environment-driven configuration for the FastAPI ML Serving microservice.

Notes:
- `MODEL_STAGE` is intentionally removed in favor of MLflow 2.x `MODEL_ALIAS` (`production` / `staging`).
- Includes S3 / MinIO artifact store settings (`MLFLOW_S3_ENDPOINT_URL`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from ml.common.artifact_contract import PRODUCTION_ALIAS, REGISTERED_MODEL_NAME
from ml.common.paths import ML_DIR


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class ServingSettings:
    """Immutable runtime configuration loaded from environment variables."""

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    environment: str = "development"
    log_level: str = "INFO"

    # MLflow Registry & Artifact Store (MinIO S3)
    mlflow_tracking_uri: str = "http://localhost:5000"
    mlflow_s3_endpoint_url: str = "http://localhost:9000"
    aws_access_key_id: str = "minioadmin"
    aws_secret_access_key: str = "changeme_minio"
    model_name: str = REGISTERED_MODEL_NAME
    model_alias: str = PRODUCTION_ALIAS

    # Background loader resilience
    startup_load_enabled: bool = True
    loader_initial_backoff_seconds: float = 1.0
    loader_max_backoff_seconds: float = 30.0
    loader_max_attempts: int = 0  # 0 = retry indefinitely in background until loaded

    # Visualization static artifacts produced by Role 4 (Person 2)
    viz_data_dir: Path = ML_DIR / "visualization" / "data"
    viz_max_points: int = 2000

    # Optional cluster-internal authentication header (X-Internal-Api-Key)
    internal_api_key: str = ""

    @property
    def derived_stage(self) -> str:
        """Map MLflow 2.x alias to the legacy stage string required by PredictResponse.model.stage."""
        alias_lower = self.model_alias.strip().lower()
        if alias_lower == "production":
            return "Production"
        if alias_lower == "staging":
            return "Staging"
        return "Production"

    @classmethod
    def from_env(cls) -> ServingSettings:
        viz_dir_raw = os.environ.get("VIZ_DATA_DIR", "").strip()
        viz_dir = Path(viz_dir_raw) if viz_dir_raw else (ML_DIR / "visualization" / "data")
        return cls(
            host=os.environ.get("HOST", "0.0.0.0").strip(),
            port=_env_int("PORT", 8000),
            environment=os.environ.get("ENVIRONMENT", "development").strip(),
            log_level=os.environ.get("LOG_LEVEL", "INFO").strip().upper(),
            mlflow_tracking_uri=os.environ.get(
                "MLFLOW_TRACKING_URI", "http://localhost:5000"
            ).strip(),
            mlflow_s3_endpoint_url=os.environ.get(
                "MLFLOW_S3_ENDPOINT_URL", "http://localhost:9000"
            ).strip(),
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", "minioadmin").strip(),
            aws_secret_access_key=os.environ.get(
                "AWS_SECRET_ACCESS_KEY", "changeme_minio"
            ).strip(),
            model_name=os.environ.get("MODEL_NAME", REGISTERED_MODEL_NAME).strip(),
            model_alias=os.environ.get("MODEL_ALIAS", PRODUCTION_ALIAS).strip().lower(),
            startup_load_enabled=_env_bool("STARTUP_LOAD_ENABLED", True),
            loader_initial_backoff_seconds=_env_float("LOADER_INITIAL_BACKOFF_SECONDS", 1.0),
            loader_max_backoff_seconds=_env_float("LOADER_MAX_BACKOFF_SECONDS", 30.0),
            loader_max_attempts=_env_int("LOADER_MAX_ATTEMPTS", 0),
            viz_data_dir=viz_dir,
            viz_max_points=_env_int("VIZ_MAX_POINTS", 2000),
            internal_api_key=os.environ.get("INTERNAL_API_KEY", "").strip(),
        )
