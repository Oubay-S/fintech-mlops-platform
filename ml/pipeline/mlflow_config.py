"""Centralized MLflow configuration, exit codes, threshold loading, and atomic artifact resolution."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ml.common.artifact_contract import (
    CANDIDATE_ALIAS,
    DATA_SOURCE_TAG,
    DEFAULT_EXPERIMENT_NAME,
    MODEL_ARTIFACT_PATH,
    PREVIOUS_ALIAS,
    PRODUCTION_ALIAS,
    REGISTERED_MODEL_NAME,
    STAGING_ALIAS,
    STATISTICAL_VALIDATION_ARTIFACT,
    UNCERTAINTY_CONFIG_ARTIFACT,
    UNCERTAINTY_SHA256_TAG,
    compute_uncertainty_sha256,
)

REPO_ROOT: Path = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# Standardized CLI Exit Codes (POSIX / CI-CD Contract)
# ---------------------------------------------------------------------------
EXIT_SUCCESS: int = 0
EXIT_GATE_FAILURE: int = 1
EXIT_INFRA_ERROR: int = 2

DEFAULT_THRESHOLDS_PATH: Path = Path(__file__).resolve().parent / "gate_thresholds.yaml"


class PipelineInfraError(RuntimeError):
    """Raised on infrastructure, syntax, MLflow connectivity, or missing-artifact errors (exit 2)."""


class PipelineGateError(RuntimeError):
    """Raised when a business metric, statistical test, or governance rule fails (exit 1)."""


@dataclass(frozen=True)
class GateThresholds:
    """Externalized validation and governance thresholds loaded from `gate_thresholds.yaml`."""

    schema_version: str
    model_name: str
    experiment_name: str
    min_pr_auc: float
    min_roc_auc: float
    min_f1: float
    min_recall: float
    max_brier_score: float
    max_expected_review_rate: float
    max_inference_p95_ms: float
    require_empirical_coverage: bool
    finite_sample_tolerance: float
    statistical_validation_required: bool
    statistical_artifact_name: str
    max_friedman_p_value: float
    require_wilcoxon_holm_superiority: bool
    max_wilcoxon_holm_p_value: float
    forbidden_production_data_sources: tuple[str, ...] = field(default_factory=tuple)
    required_run_tags: tuple[str, ...] = field(default_factory=tuple)


def load_gate_thresholds(path: str | Path | None = None) -> GateThresholds:
    """Load and validate externalized thresholds from `gate_thresholds.yaml`."""
    resolved = Path(path) if path is not None else DEFAULT_THRESHOLDS_PATH
    if not resolved.exists() or not resolved.is_file():
        raise PipelineInfraError(f"Thresholds configuration file not found: {resolved}")

    try:
        raw = yaml.safe_load(resolved.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise TypeError("Root of gate_thresholds.yaml must be a mapping.")

        perf = raw["performance_metrics"]
        ops = raw["operational_budgets"]
        conf = raw["conformal_validation"]
        stat = raw["statistical_validation"]
        promo = raw["promotion_policy"]

        return GateThresholds(
            schema_version=str(raw.get("schema_version", "1.0")),
            model_name=str(raw.get("model_name", REGISTERED_MODEL_NAME)),
            experiment_name=str(raw.get("experiment_name", DEFAULT_EXPERIMENT_NAME)),
            min_pr_auc=float(perf["min_pr_auc"]),
            min_roc_auc=float(perf["min_roc_auc"]),
            min_f1=float(perf["min_f1"]),
            min_recall=float(perf["min_recall"]),
            max_brier_score=float(perf["max_brier_score"]),
            max_expected_review_rate=float(ops["max_expected_review_rate"]),
            max_inference_p95_ms=float(ops["max_inference_p95_ms"]),
            require_empirical_coverage=bool(conf["require_empirical_coverage"]),
            finite_sample_tolerance=float(conf["finite_sample_tolerance"]),
            statistical_validation_required=bool(stat["required"]),
            statistical_artifact_name=str(
                stat.get("artifact_name", STATISTICAL_VALIDATION_ARTIFACT)
            ),
            max_friedman_p_value=float(stat["max_friedman_p_value"]),
            require_wilcoxon_holm_superiority=bool(
                stat["require_wilcoxon_holm_superiority"]
            ),
            max_wilcoxon_holm_p_value=float(
                stat.get("max_wilcoxon_holm_p_value", stat["max_friedman_p_value"])
            ),
            forbidden_production_data_sources=tuple(
                str(s).strip().lower()
                for s in promo.get("forbidden_production_data_sources", [])
            ),
            required_run_tags=tuple(
                str(t).strip() for t in promo.get("required_run_tags", [])
            ),
        )
    except Exception as exc:
        raise PipelineInfraError(
            f"Invalid gate_thresholds.yaml at '{resolved}': {exc}"
        ) from exc


def load_dotenv_if_present(dotenv_path: Path | None = None) -> None:
    """Load key=value pairs from `.env` into `os.environ` without overwriting existing vars."""
    env_file = dotenv_path or (REPO_ROOT / ".env")
    if not env_file.exists() or not env_file.is_file():
        return
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        k = key.strip()
        v = value.strip().strip('"').strip("'")
        if k:
            os.environ.setdefault(k, v)


def resolve_tracking_uri(cli_uri: str | None = None) -> str:
    """Resolve MLflow tracking URI from CLI argument, `MLFLOW_TRACKING_URI` env var, or `.env`."""
    load_dotenv_if_present()
    uri = (cli_uri or os.getenv("MLFLOW_TRACKING_URI") or "").strip()
    if not uri:
        return "http://localhost:5000"
    return uri


def get_git_sha() -> str:
    """Return the current git commit SHA or `'unknown'` if git is unavailable."""
    env_sha = os.getenv("GIT_SHA", "").strip()
    if env_sha:
        return env_sha
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


@dataclass(frozen=True)
class ResolvedTargetRun:
    """Atomically resolved MLflow Run and optional Registry ModelVersion."""

    run_id: str
    run: Any
    model_name: str
    model_version: str | None
    alias: str | None


def resolve_target_run(
    *,
    tracking_uri: str,
    model_name: str = REGISTERED_MODEL_NAME,
    alias: str | None = None,
    run_id: str | None = None,
) -> ResolvedTargetRun:
    """Resolve an MLflow Run atomically from either `--alias` or `--run-id`."""
    try:
        import mlflow
        from mlflow.tracking import MlflowClient
    except ImportError as exc:
        raise PipelineInfraError(f"MLflow is not installed: {exc}") from exc

    if not alias and not run_id:
        raise PipelineInfraError("Either --alias or --run-id must be provided.")

    try:
        mlflow.set_tracking_uri(tracking_uri)
        client = MlflowClient(tracking_uri=tracking_uri)

        resolved_version: str | None = None
        resolved_alias: str | None = alias.strip().lower() if alias else None

        if resolved_alias:
            mv = client.get_model_version_by_alias(
                name=model_name, alias=resolved_alias
            )
            resolved_version = str(mv.version)
            resolved_run_id = str(mv.run_id)
        else:
            resolved_run_id = str(run_id).strip()
            versions = client.search_model_versions(f"name='{model_name}'")
            for v in versions:
                if str(v.run_id) == resolved_run_id:
                    resolved_version = str(v.version)
                    break

        run = client.get_run(resolved_run_id)
        return ResolvedTargetRun(
            run_id=resolved_run_id,
            run=run,
            model_name=model_name,
            model_version=resolved_version,
            alias=resolved_alias,
        )
    except Exception as exc:
        raise PipelineInfraError(
            f"Failed to resolve target from MLflow ({tracking_uri}): {exc}"
        ) from exc


def download_json_artifact(
    *,
    tracking_uri: str,
    run_id: str,
    artifact_path: str,
) -> tuple[dict[str, Any], bytes]:
    """Download and parse a JSON artifact from a specific MLflow `run_id`."""
    try:
        from mlflow.tracking import MlflowClient

        client = MlflowClient(tracking_uri=tracking_uri)
        with tempfile.TemporaryDirectory(prefix="mlops_artifact_") as tmp_dir:
            local_file = Path(
                client.download_artifacts(
                    run_id=run_id,
                    path=artifact_path,
                    dst_path=tmp_dir,
                )
            )
            if not local_file.exists() or not local_file.is_file():
                raise FileNotFoundError(
                    f"Artifact '{artifact_path}' does not exist in run '{run_id}'."
                )
            raw_bytes = local_file.read_bytes()
            parsed = json.loads(raw_bytes.decode("utf-8"))
            if not isinstance(parsed, dict):
                raise TypeError(
                    f"Artifact '{artifact_path}' in run '{run_id}' must be a JSON object."
                )
            return parsed, raw_bytes
    except Exception as exc:
        raise PipelineInfraError(
            f"Unable to download or parse artifact '{artifact_path}' for run '{run_id}': {exc}"
        ) from exc


__all__ = [
    "CANDIDATE_ALIAS",
    "DATA_SOURCE_TAG",
    "DEFAULT_EXPERIMENT_NAME",
    "DEFAULT_THRESHOLDS_PATH",
    "EXIT_GATE_FAILURE",
    "EXIT_INFRA_ERROR",
    "EXIT_SUCCESS",
    "MODEL_ARTIFACT_PATH",
    "PREVIOUS_ALIAS",
    "PRODUCTION_ALIAS",
    "REGISTERED_MODEL_NAME",
    "STAGING_ALIAS",
    "STATISTICAL_VALIDATION_ARTIFACT",
    "UNCERTAINTY_CONFIG_ARTIFACT",
    "UNCERTAINTY_SHA256_TAG",
    "GateThresholds",
    "PipelineGateError",
    "PipelineInfraError",
    "ResolvedTargetRun",
    "compute_uncertainty_sha256",
    "download_json_artifact",
    "get_git_sha",
    "load_gate_thresholds",
    "resolve_target_run",
    "resolve_tracking_uri",
]
