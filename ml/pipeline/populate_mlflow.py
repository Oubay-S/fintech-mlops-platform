"""Populate MLflow with Phase 4 Benchmark runs and Champion Candidate Model.

Connects to the configured MLflow tracking server and S3/MinIO store (via
environment variables or `.env`) to:
1. Ensure the `paysim-fraud-benchmark` experiment exists.
2. Log the 4 comparison models (`lr`, `rf`, `svm`, `mlp`) from
   `ml/training/results/benchmark_runs.csv`.
3. Strictly load the real PaySim-trained Champion XGBoost model from
   `ml/data/processed/final_contract_model.joblib` and log it with:
   - 14-column contract Pipeline (`preprocessor` + `classifier`)
   - `uncertainty_config.json`
   - `statistical_validation.json` (Friedman & Wilcoxon/Holm results)
   - Mandatory tags (`data_source`, `uncertainty_config_sha256`,
     `algorithm=xgboost`, dynamic `git_sha`)
4. Register the model under `fraud-detector` with the `@candidate` alias.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
from pathlib import Path

# Ensure UTF-8 stdout on Windows consoles for MLflow client output
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import joblib
import mlflow
import mlflow.sklearn
import pandas as pd
from mlflow.tracking import MlflowClient
from sklearn.pipeline import Pipeline
from sklearn.utils.validation import check_is_fitted
from xgboost import XGBClassifier

from ml.common.artifact_contract import (
    CANDIDATE_ALIAS,
    DATA_SOURCE_TAG,
    DEFAULT_EXPERIMENT_NAME,
    EXPECTED_TRANSFORMED_FEATURES,
    MODEL_ARTIFACT_PATH,
    REGISTERED_MODEL_NAME,
    UNCERTAINTY_SHA256_TAG,
    UncertaintyConfig,
    compute_uncertainty_sha256,
)
from ml.pipeline.mlflow_config import (
    EXIT_INFRA_ERROR,
    EXIT_SUCCESS,
    REPO_ROOT,
    PipelineInfraError,
    get_git_sha,
    resolve_tracking_uri,
)

BENCHMARK_CSV_PATH = REPO_ROOT / "ml" / "training" / "results" / "benchmark_runs.csv"
STATISTICS_JSON_PATH = (
    REPO_ROOT / "ml" / "training" / "results" / "statistical_validation.json"
)
UNCERTAINTY_JSON_PATH = (
    REPO_ROOT / "ml" / "training" / "package" / "uncertainty_config.json"
)
LOCAL_MODEL_PATH = (
    REPO_ROOT / "ml" / "data" / "processed" / "final_contract_model.joblib"
)

REQUIRED_CHAMPION_METRICS: tuple[str, ...] = (
    "roc_auc",
    "pr_auc",
    "f1",
    "precision",
    "recall",
    "mcc",
    "brier_score",
    "coverage_legit",
    "coverage_fraud",
    "expected_review_rate",
    "inference_p95_ms",
)


def _is_finite_number(val: object) -> bool:
    """Return True iff `val` is a genuine finite `int` or `float` (explicitly rejecting `bool`)."""
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        return False
    return math.isfinite(float(val))


def load_champion_pipeline(
    local_model_path: Path = LOCAL_MODEL_PATH,
) -> Pipeline:
    """Strictly load and validate the real PaySim-trained Champion Pipeline from disk.

    Raises `PipelineInfraError` if the `.joblib` file does not exist, is not a
    fitted scikit-learn `Pipeline` with an `XGBClassifier`, or does not match
    the 14-column transformed feature contract. Never builds a surrogate model.
    """
    if not local_model_path.exists():
        raise PipelineInfraError(
            f"Real trained model not found at '{local_model_path}'. "
            "No surrogate or fallback model is permitted. "
            "Run 'python -m ml.pipeline.fetch_model' to download and verify the "
            "official release model artifact into 'ml/data/processed/'."
        )

    try:
        loaded = joblib.load(local_model_path)
    except Exception as exc:
        raise PipelineInfraError(
            f"Failed to deserialize model artifact at '{local_model_path}': {exc}"
        ) from exc

    if isinstance(loaded, dict) and isinstance(loaded.get("pipeline"), Pipeline):
        pipeline: Pipeline = loaded["pipeline"]
    elif isinstance(loaded, Pipeline):
        pipeline = loaded
    else:
        raise PipelineInfraError(
            f"Invalid model structure in '{local_model_path}': expected a "
            "scikit-learn Pipeline or dict with key 'pipeline', got "
            f"{type(loaded).__name__}."
        )

    if (
        "preprocessor" not in pipeline.named_steps
        or "classifier" not in pipeline.named_steps
    ):
        raise PipelineInfraError(
            f"Pipeline in '{local_model_path}' is missing required steps "
            f"('preprocessor', 'classifier'); found {list(pipeline.named_steps.keys())}."
        )

    preprocessor = pipeline.named_steps["preprocessor"]
    classifier = pipeline.named_steps["classifier"]

    if not isinstance(classifier, XGBClassifier):
        raise PipelineInfraError(
            f"Champion pipeline classifier in '{local_model_path}' must be an "
            f"XGBClassifier; got {type(classifier).__name__}."
        )

    try:
        check_is_fitted(pipeline)
        check_is_fitted(preprocessor)
        check_is_fitted(classifier)
        transformed_names = [str(col) for col in preprocessor.get_feature_names_out()]
    except Exception as exc:
        raise PipelineInfraError(
            f"Pipeline in '{local_model_path}' is not fitted or failed validation: {exc}"
        ) from exc

    if transformed_names != list(EXPECTED_TRANSFORMED_FEATURES):
        raise PipelineInfraError(
            f"Pipeline preprocessor feature signature mismatch in '{local_model_path}': "
            f"expected {list(EXPECTED_TRANSFORMED_FEATURES)}, got {transformed_names}."
        )

    return pipeline


def _extract_benchmark_metrics(df: pd.DataFrame, model_code: str) -> dict[str, float]:
    """Compute genuine mean cross-validation metrics for `model_code` under contract protocol.

    Strictly reads columns from `benchmark_runs.csv` without fabricating any
    missing metrics. Raises `PipelineInfraError` if `model_code` has no rows.
    """
    if "protocol" not in df.columns or "model" not in df.columns:
        raise PipelineInfraError(
            f"'{BENCHMARK_CSV_PATH}' is missing required 'protocol' or 'model' columns."
        )

    contract_df = df[df["protocol"] == "contract"]
    m_df = contract_df[contract_df["model"] == model_code]
    if m_df.empty:
        raise PipelineInfraError(
            f"No benchmark rows found for model='{model_code}' with protocol='contract' "
            f"in '{BENCHMARK_CSV_PATH}'."
        )

    means = m_df.mean(numeric_only=True).to_dict()
    metrics: dict[str, float] = {}
    metric_map = {
        "roc_auc": "roc_auc",
        "pr_auc": "pr_auc",
        "f1": "f1",
        "precision": "precision",
        "recall": "recall",
        "mcc": "mcc",
        "brier": "brier_score",
        "brier_score": "brier_score",
        "fit_sec": "fit_sec",
        "predict_ms_per_row": "predict_ms_per_row",
    }
    for src_col, dst_metric in metric_map.items():
        if src_col in means and _is_finite_number(means[src_col]):
            metrics[dst_metric] = float(means[src_col])

    required_benchmark_cols = (
        "roc_auc",
        "pr_auc",
        "f1",
        "precision",
        "recall",
        "mcc",
        "brier_score",
    )
    missing = [col for col in required_benchmark_cols if col not in metrics]
    if missing:
        raise PipelineInfraError(
            f"Benchmark model '{model_code}' in '{BENCHMARK_CSV_PATH}' is missing "
            f"required finite metric columns: {missing}."
        )
    return metrics


def _extract_champion_metrics(cfg_dict: dict[str, object]) -> dict[str, float]:
    """Strictly extract verified Champion metrics from `uncertainty_config.json`.

    Raises `PipelineInfraError` if `metrics_summary` or any mandatory metric is
    missing, boolean, or non-finite.
    """
    summary = cfg_dict.get("metrics_summary")
    if not isinstance(summary, dict):
        raise PipelineInfraError(
            f"'{UNCERTAINTY_JSON_PATH}' is missing a valid 'metrics_summary' object."
        )

    missing = [
        key
        for key in REQUIRED_CHAMPION_METRICS
        if key not in summary or not _is_finite_number(summary[key])
    ]
    if missing:
        raise PipelineInfraError(
            f"'{UNCERTAINTY_JSON_PATH}' metrics_summary is missing required finite numeric "
            f"metrics: {missing}. Refusing to fabricate or fallback metrics."
        )

    invalid_extra = [
        key
        for key, val in summary.items()
        if isinstance(val, bool)
        or (isinstance(val, (int, float)) and not math.isfinite(float(val)))
    ]
    if invalid_extra:
        raise PipelineInfraError(
            f"'{UNCERTAINTY_JSON_PATH}' metrics_summary contains invalid boolean or "
            f"non-finite metric values for keys: {invalid_extra}."
        )

    return {key: float(val) for key, val in summary.items() if _is_finite_number(val)}


def populate(
    tracking_uri: str | None = None,
    local_model_path: Path = LOCAL_MODEL_PATH,
) -> None:
    """Populate benchmark runs and register the `@candidate` champion model in MLflow."""
    for required_file in (
        BENCHMARK_CSV_PATH,
        UNCERTAINTY_JSON_PATH,
        STATISTICS_JSON_PATH,
    ):
        if not required_file.exists():
            raise PipelineInfraError(
                f"Required training artifact not found: '{required_file}'."
            )

    # Validate the real trained model and artifacts BEFORE modifying MLflow state
    pipeline = load_champion_pipeline(local_model_path=local_model_path)
    try:
        df = pd.read_csv(BENCHMARK_CSV_PATH)
    except Exception as exc:
        raise PipelineInfraError(
            f"Failed to parse benchmark CSV '{BENCHMARK_CSV_PATH}': {exc}"
        ) from exc

    benchmark_runs_metrics = {
        model_name: _extract_benchmark_metrics(df, model_name)
        for model_name in ("lr", "rf", "svm", "mlp")
    }
    _extract_benchmark_metrics(df, "xgb")

    try:
        cfg_dict = json.loads(UNCERTAINTY_JSON_PATH.read_text(encoding="utf-8"))
        if not isinstance(cfg_dict, dict):
            raise TypeError("Top-level JSON value must be an object.")
        uncertainty_config = UncertaintyConfig.from_dict(cfg_dict)
        cfg_sha256 = compute_uncertainty_sha256(uncertainty_config)
    except PipelineInfraError:
        raise
    except Exception as exc:
        raise PipelineInfraError(
            f"Invalid uncertainty configuration at '{UNCERTAINTY_JSON_PATH}': {exc}"
        ) from exc

    champion_metrics = _extract_champion_metrics(cfg_dict)

    dataset_version = cfg_dict.get("dataset_version")
    if not isinstance(dataset_version, str) or not dataset_version.strip():
        raise PipelineInfraError(
            f"'{UNCERTAINTY_JSON_PATH}' is missing required non-empty 'dataset_version'."
        )

    try:
        resolved_uri = resolve_tracking_uri(tracking_uri)
        mlflow.set_tracking_uri(resolved_uri)
        client = MlflowClient(tracking_uri=resolved_uri)

        exp = client.get_experiment_by_name(DEFAULT_EXPERIMENT_NAME)
        if exp is None:
            exp_id = client.create_experiment(DEFAULT_EXPERIMENT_NAME)
            print(f"Created experiment '{DEFAULT_EXPERIMENT_NAME}' (ID: {exp_id})")
        else:
            exp_id = exp.experiment_id
            print(
                f"Using existing experiment '{DEFAULT_EXPERIMENT_NAME}' (ID: {exp_id})"
            )
            for r in client.search_runs(exp_id):
                try:
                    client.delete_run(r.info.run_id)
                except Exception:  # noqa: BLE001, S110
                    pass

        # 1. Log benchmark runs from benchmark_runs.csv
        for model_name, mean_metrics in benchmark_runs_metrics.items():
            with mlflow.start_run(
                experiment_id=exp_id, run_name=f"benchmark-{model_name}"
            ):
                mlflow.log_param("algorithm", model_name)
                mlflow.log_param("protocol", "contract")
                mlflow.log_param("model_family", "benchmark_evaluation")
                for k, v in mean_metrics.items():
                    mlflow.log_metric(k, float(v))
            print(f"Logged benchmark run for algorithm: {model_name}")

        # 2. Log the real PaySim-trained Champion XGBoost model and contract artifacts
        classifier = pipeline.named_steps["classifier"]
        model_seed = classifier.get_params().get("random_state")
        if model_seed is None:
            raise PipelineInfraError(
                "Trained classifier is missing a valid 'random_state' seed parameter."
            )

        champion_tags = {
            "algorithm": str(uncertainty_config.algorithm),
            DATA_SOURCE_TAG: dataset_version,
            UNCERTAINTY_SHA256_TAG: cfg_sha256,
            "dataset_version": dataset_version,
            "git_sha": get_git_sha(),
            "seed": str(model_seed),
            "conformal_method": str(uncertainty_config.method),
            "confidence_level": str(uncertainty_config.confidence_level),
        }

        with mlflow.start_run(
            experiment_id=exp_id, run_name="champion-xgboost-candidate"
        ) as run:
            run_id = run.info.run_id
            for k, v in champion_tags.items():
                mlflow.set_tag(k, v)
            for k, v in champion_metrics.items():
                mlflow.log_metric(k, float(v))

            mlflow.log_artifact(str(UNCERTAINTY_JSON_PATH), artifact_path="")
            mlflow.log_artifact(str(STATISTICS_JSON_PATH), artifact_path="")

            # Save and upload model directory compatible with MLflow 2.16.2 server
            with tempfile.TemporaryDirectory(prefix="mlflow_model_") as tmp_dir:
                model_dir = os.path.join(tmp_dir, "model")
                mlflow.sklearn.save_model(
                    sk_model=pipeline,
                    path=model_dir,
                    serialization_format="cloudpickle",
                )
                mlflow.log_artifacts(model_dir, artifact_path=MODEL_ARTIFACT_PATH)

        # 3. Register model version in MLflow Model Registry under @candidate
        try:
            client.create_registered_model(REGISTERED_MODEL_NAME)
        except Exception:  # noqa: BLE001, S110
            pass

        mv = client.create_model_version(
            name=REGISTERED_MODEL_NAME,
            source=f"{run.info.artifact_uri}/{MODEL_ARTIFACT_PATH}",
            run_id=run_id,
        )
        version = str(mv.version)

        client.set_registered_model_alias(
            name=REGISTERED_MODEL_NAME,
            alias=CANDIDATE_ALIAS,
            version=version,
        )
        print(
            f"SUCCESS: Champion XGBoost registered under '{REGISTERED_MODEL_NAME}' "
            f"v{version} with alias @{CANDIDATE_ALIAS} (Run ID: {run_id})"
        )
    except PipelineInfraError:
        raise
    except Exception as exc:
        raise PipelineInfraError(
            f"MLflow tracking or registry operation failed: {exc}"
        ) from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tracking-uri",
        default=None,
        help="MLflow tracking URI override (defaults to MLFLOW_TRACKING_URI or .env)",
    )
    parser.add_argument(
        "--model-path",
        default=str(LOCAL_MODEL_PATH),
        help="Path to the real trained final_contract_model.joblib artifact",
    )
    args = parser.parse_args(argv)
    try:
        populate(
            tracking_uri=args.tracking_uri,
            local_model_path=Path(args.model_path),
        )
        return EXIT_SUCCESS
    except Exception as exc:  # noqa: BLE001
        infra_exc = (
            exc
            if isinstance(exc, PipelineInfraError)
            else PipelineInfraError(f"Unexpected populate_mlflow failure: {exc}")
        )
        print(
            json.dumps(
                {
                    "status": "INFRA_ERROR",
                    "exit_code": EXIT_INFRA_ERROR,
                    "error": str(infra_exc),
                },
                indent=2,
            ),
            file=sys.stderr,
        )
        return EXIT_INFRA_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
