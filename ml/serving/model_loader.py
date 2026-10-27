"""Isolated MLflow Model Registry loader with background retry/backoff resilience.

Loads a registered model by alias (`models:/{model_name}@{model_alias}`) along with
its companion `uncertainty_config.json` artifact from the same MLflow run.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from pathlib import Path

from ml.common.artifact_contract import (
    MODEL_ARTIFACT_PATH,
    UNCERTAINTY_CONFIG_ARTIFACT,
    UncertaintyConfigContract,
)
from ml.common.schema import FEATURE_COLUMNS

from .config import ServingSettings
from .metrics import record_model_loaded, record_model_unloaded
from .predictor import ModelNotReadyError, Predictor, TrainedModelPredictor

logger = logging.getLogger("ml.serving.loader")


class MLflowModelLoader:
    """Loads a trained sklearn pipeline and `uncertainty_config.json` from MLflow by alias."""

    def __init__(self, settings: ServingSettings) -> None:
        self._settings = settings

    def _configure_environment(self) -> None:
        if self._settings.mlflow_s3_endpoint_url:
            os.environ.setdefault(
                "MLFLOW_S3_ENDPOINT_URL", self._settings.mlflow_s3_endpoint_url
            )
        if self._settings.aws_access_key_id:
            os.environ.setdefault("AWS_ACCESS_KEY_ID", self._settings.aws_access_key_id)
        if self._settings.aws_secret_access_key:
            os.environ.setdefault(
                "AWS_SECRET_ACCESS_KEY", self._settings.aws_secret_access_key
            )

    def load_by_alias(
        self,
        *,
        model_name: str | None = None,
        model_alias: str | None = None,
        tracking_uri: str | None = None,
    ) -> TrainedModelPredictor:
        """Load the registered model and companion uncertainty config from MLflow."""
        import mlflow
        from mlflow.tracking import MlflowClient

        self._configure_environment()
        resolved_uri = tracking_uri or self._settings.mlflow_tracking_uri
        resolved_name = model_name or self._settings.model_name
        resolved_alias = (model_alias or self._settings.model_alias).strip().lower()

        mlflow.set_tracking_uri(resolved_uri)
        client = MlflowClient(tracking_uri=resolved_uri)

        mv = client.get_model_version_by_alias(name=resolved_name, alias=resolved_alias)
        version_str = str(mv.version)
        run_id = str(mv.run_id)

        with tempfile.TemporaryDirectory(prefix="mlflow_uncertainty_") as tmp_dir:
            config_local_path = Path(
                client.download_artifacts(
                    run_id=run_id,
                    path=UNCERTAINTY_CONFIG_ARTIFACT,
                    dst_path=tmp_dir,
                )
            )
            raw_config = json.loads(config_local_path.read_text(encoding="utf-8"))
            uncertainty_config = UncertaintyConfigContract.from_dict(raw_config)

        # Load the trained sklearn pipeline by model alias URI
        model_uri = f"models:/{resolved_name}@{resolved_alias}"
        try:
            sk_model = mlflow.sklearn.load_model(model_uri=model_uri)
        except Exception:  # noqa: BLE001
            # Fallback to run-relative artifact path if storage URI uses local file scheme
            sk_model = mlflow.sklearn.load_model(
                model_uri=f"runs:/{run_id}/{MODEL_ARTIFACT_PATH}"
            )

        # Validate preprocessor feature names if exposed on the pipeline
        named_steps = getattr(sk_model, "named_steps", {})
        preprocessor = named_steps.get("preprocessor")
        if preprocessor is not None and hasattr(preprocessor, "feature_names_in_"):
            fitted_in = [str(c) for c in preprocessor.feature_names_in_]
            if fitted_in != list(FEATURE_COLUMNS):
                raise ValueError(
                    f"Trained preprocessor feature_names_in_ {fitted_in} "
                    f"does not match FEATURE_COLUMNS {FEATURE_COLUMNS}"
                )

        return TrainedModelPredictor(
            model=sk_model,
            uncertainty_config=uncertainty_config,
            model_name=resolved_name,
            model_version=version_str,
            model_alias=resolved_alias,
            run_id=run_id,
        )


class ModelRegistryHolder:
    """Thread-safe container holding the active `Predictor` instance and background loader thread."""

    def __init__(self, settings: ServingSettings, loader: MLflowModelLoader | None = None) -> None:
        self._settings = settings
        self._loader = loader or MLflowModelLoader(settings)
        self._lock = threading.RLock()
        self._predictor: Predictor | None = None
        self._stop_event = threading.Event()
        self._bg_thread: threading.Thread | None = None

    @property
    def is_ready(self) -> bool:
        with self._lock:
            return self._predictor is not None

    def get_predictor(self) -> Predictor:
        """Return the loaded `Predictor` or raise `ModelNotReadyError`."""
        with self._lock:
            if self._predictor is None:
                raise ModelNotReadyError(
                    f"Model '{self._settings.model_name}@{self._settings.model_alias}' "
                    "is not loaded yet; readiness probe is not ready."
                )
            return self._predictor

    def set_predictor(self, predictor: Predictor, load_seconds: float = 0.0) -> None:
        """Atomically set the active predictor and update Prometheus readiness gauges."""
        with self._lock:
            self._predictor = predictor
            record_model_loaded(predictor.get_model_ref(), load_seconds)

    def clear_predictor(self) -> None:
        """Unload the active predictor (sets `ml_ready` gauge to 0)."""
        with self._lock:
            self._predictor = None
            record_model_unloaded()

    def try_load_once(self) -> bool:
        """Attempt a single synchronous load from MLflow Registry. Never raises."""
        start = time.perf_counter()
        try:
            predictor = self._loader.load_by_alias()
            elapsed = time.perf_counter() - start
            self.set_predictor(predictor, load_seconds=elapsed)
            logger.info(
                json.dumps(
                    {
                        "event": "model_loaded",
                        "model_name": predictor.get_model_ref().name,
                        "model_version": predictor.get_model_ref().version,
                        "alias": predictor.get_model_ref().alias.value,
                        "load_seconds": round(elapsed, 4),
                    }
                )
            )
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                json.dumps(
                    {
                        "event": "model_load_failed",
                        "model_name": self._settings.model_name,
                        "alias": self._settings.model_alias,
                        "error": str(exc),
                    }
                )
            )
            return False

    def _background_load_loop(self) -> None:
        backoff = max(self._settings.loader_initial_backoff_seconds, 0.05)
        max_backoff = max(self._settings.loader_max_backoff_seconds, backoff)
        max_attempts = self._settings.loader_max_attempts
        attempt = 0

        while not self._stop_event.is_set() and not self.is_ready:
            attempt += 1
            if self.try_load_once():
                return
            if max_attempts > 0 and attempt >= max_attempts:
                return
            if self._stop_event.wait(timeout=backoff):
                return
            backoff = min(backoff * 2.0, max_backoff)

    def start_background_load(self) -> None:
        """Start non-blocking background loader thread if not already loaded."""
        if self.is_ready or not self._settings.startup_load_enabled:
            return
        self._stop_event.clear()
        self._bg_thread = threading.Thread(
            target=self._background_load_loop,
            name="mlflow-model-loader",
            daemon=True,
        )
        self._bg_thread.start()

    def stop_background_load(self, timeout: float = 2.0) -> None:
        """Signal the background loader thread to stop cleanly."""
        self._stop_event.set()
        if self._bg_thread is not None and self._bg_thread.is_alive():
            self._bg_thread.join(timeout=timeout)
