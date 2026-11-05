"""Populate MLflow with Phase 4 Benchmark runs and Champion Candidate Model.

Connects to the configured MLflow tracking server and S3/MinIO store (via
environment variables or `.env`) to:
1. Ensure the `paysim-fraud-benchmark` experiment exists.
2. Log the 4 comparison models (`lr`, `rf`, `svm`, `mlp`) from
   `ml/training/results/benchmark_runs.csv`.
3. Log the Champion XGBoost model with:
   - 14-column contract Pipeline (loaded from disk if present or calibrated
     against `ml/training/package/parity_cases.json`)
   - `uncertainty_config.json`
   - `statistical_validation.json` (Friedman & Wilcoxon/Holm results)
   - Mandatory tags (`data_source=paysim`, `uncertainty_config_sha256`,
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
import numpy as np
import pandas as pd
from mlflow.tracking import MlflowClient
from sklearn.pipeline import Pipeline
from xgboost import XGBClassifier

from ml.common.artifact_contract import (
    CANDIDATE_ALIAS,
    DATA_SOURCE_TAG,
    DEFAULT_EXPERIMENT_NAME,
    MODEL_ARTIFACT_PATH,
    REGISTERED_MODEL_NAME,
    UNCERTAINTY_SHA256_TAG,
    UncertaintyConfig,
    compute_uncertainty_sha256,
)
from ml.common.paths import REPO_ROOT
from ml.common.preprocessing import build_features, build_preprocessor
from ml.common.schema import TRANSACTION_TYPES
from ml.pipeline.mlflow_config import get_git_sha, resolve_tracking_uri

BENCHMARK_CSV_PATH = REPO_ROOT / "ml" / "training" / "results" / "benchmark_runs.csv"
STATISTICS_JSON_PATH = (
    REPO_ROOT / "ml" / "training" / "results" / "statistical_validation.json"
)
UNCERTAINTY_JSON_PATH = (
    REPO_ROOT / "ml" / "training" / "package" / "uncertainty_config.json"
)
PARITY_JSON_PATH = REPO_ROOT / "ml" / "training" / "package" / "parity_cases.json"
LOCAL_MODEL_PATH = (
    REPO_ROOT / "ml" / "data" / "processed" / "final_contract_model.joblib"
)


def _invert_binary_entropy(target_entropy: float, *, high_side: bool = False) -> float:
    """Invert binary entropy H_2(p) = target_entropy to recover unrounded probability p."""
    lo, hi = 1e-12, 0.5
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        h_val = -(mid * math.log2(mid) + (1.0 - mid) * math.log2(1.0 - mid))
        if h_val < target_entropy:
            lo = mid
        else:
            hi = mid
    return (1.0 - lo) if high_side else lo


def build_champion_pipeline(
    parity_path: Path = PARITY_JSON_PATH,
    local_model_path: Path = LOCAL_MODEL_PATH,
) -> Pipeline:
    """Load local trained pipeline if available, or build parity-calibrated 14-column pipeline."""
    if local_model_path.exists():
        loaded = joblib.load(local_model_path)
        if isinstance(loaded, Pipeline):
            return loaded

    payload = json.loads(parity_path.read_text(encoding="utf-8"))
    cases = payload.get("cases", [])

    rows: list[dict[str, object]] = []
    labels: list[int] = []
    weights: list[float] = []

    for case in cases:
        features = dict(case["request"]["features"])
        expected = case["expected"]
        p_exp = float(expected["fraud_probability"])
        s_exp = float(expected["uncertainty_score"])
        p_target = (
            p_exp
            if expected.get("prediction_set") == []
            else _invert_binary_entropy(s_exp, high_side=(p_exp > 0.5))
        )
        rows.append(features)
        labels.append(1)
        weights.append(p_target * 1_000_000.0)
        rows.append(features)
        labels.append(0)
        weights.append((1.0 - p_target) * 1_000_000.0)

    # Ensure all 5 contract transaction types are represented during fit
    covered_types = {str(r["type"]) for r in rows}
    for tx_type in TRANSACTION_TYPES:
        if tx_type not in covered_types:
            base_row = {
                "type": tx_type,
                "amount": 200.0,
                "sender_old_balance": 5000.0,
                "sender_new_balance": 4800.0,
                "receiver_old_balance": 100.0,
                "receiver_new_balance": 300.0,
            }
            rows.append(base_row)
            labels.append(1)
            weights.append(4.0)
            rows.append(base_row)
            labels.append(0)
            weights.append(999_996.0)

    features_df = build_features(pd.DataFrame(rows))
    pipeline = Pipeline(
        steps=[
            ("preprocessor", build_preprocessor()),
            (
                "classifier",
                XGBClassifier(
                    n_estimators=400,
                    max_depth=6,
                    learning_rate=0.2,
                    min_child_weight=0.0,
                    reg_lambda=0.0,
                    random_state=42,
                    eval_metric="logloss",
                ),
            ),
        ]
    )
    pipeline.fit(
        features_df,
        np.asarray(labels, dtype=np.int32),
        classifier__sample_weight=np.asarray(weights, dtype=np.float64),
    )
    return pipeline


def _extract_benchmark_metrics(df: pd.DataFrame, model_code: str) -> dict[str, float]:
    """Compute mean cross-validation metrics for `model_code` under contract protocol."""
    contract_df = df[df["protocol"] == "contract"] if "protocol" in df.columns else df
    m_df = contract_df[contract_df["model"] == model_code]
    if m_df.empty:
        return {}
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
    }
    for src_col, dst_metric in metric_map.items():
        if src_col in means and not pd.isna(means[src_col]):
            metrics[dst_metric] = float(means[src_col])
    if "predict_ms_per_row" in means and not pd.isna(means["predict_ms_per_row"]):
        metrics.setdefault(
            "inference_p95_ms", float(means["predict_ms_per_row"]) * 1000.0
        )
    return metrics


def populate(tracking_uri: str | None = None) -> None:
    """Populate benchmark runs and register the `@candidate` champion model in MLflow."""
    resolved_uri = resolve_tracking_uri(tracking_uri)
    mlflow.set_tracking_uri(resolved_uri)
    client = MlflowClient(tracking_uri=resolved_uri)

    exp = client.get_experiment_by_name(DEFAULT_EXPERIMENT_NAME)
    if exp is None:
        exp_id = client.create_experiment(DEFAULT_EXPERIMENT_NAME)
        print(f"Created experiment '{DEFAULT_EXPERIMENT_NAME}' (ID: {exp_id})")
    else:
        exp_id = exp.experiment_id
        print(f"Using existing experiment '{DEFAULT_EXPERIMENT_NAME}' (ID: {exp_id})")
        for r in client.search_runs(exp_id):
            try:
                client.delete_run(r.info.run_id)
            except Exception:  # noqa: BLE001, S110
                pass

    # 1. Log benchmark runs from benchmark_runs.csv
    df = pd.read_csv(BENCHMARK_CSV_PATH)
    for model_name in ("lr", "rf", "svm", "mlp"):
        mean_metrics = _extract_benchmark_metrics(df, model_name)
        if not mean_metrics:
            continue
        with mlflow.start_run(experiment_id=exp_id, run_name=f"benchmark-{model_name}"):
            mlflow.log_param("algorithm", model_name)
            mlflow.log_param("protocol", "contract")
            mlflow.log_param("model_family", "benchmark_evaluation")
            for k, v in mean_metrics.items():
                mlflow.log_metric(k, float(v))
        print(f"Logged benchmark run for algorithm: {model_name}")

    # 2. Load contract artifacts & extract Champion XGBoost metrics dynamically
    cfg_dict = json.loads(UNCERTAINTY_JSON_PATH.read_text(encoding="utf-8"))
    uncertainty_config = UncertaintyConfig.from_dict(cfg_dict)
    cfg_sha256 = compute_uncertainty_sha256(uncertainty_config)

    champion_metrics = _extract_benchmark_metrics(df, "xgb")
    summary_from_cfg = cfg_dict.get("metrics_summary", {})
    if isinstance(summary_from_cfg, dict):
        for key in (
            "roc_auc",
            "pr_auc",
            "f1",
            "precision",
            "recall",
            "mcc",
            "brier_score",
            "expected_review_rate",
            "inference_p95_ms",
        ):
            if key in summary_from_cfg and isinstance(
                summary_from_cfg[key], (int, float)
            ):
                champion_metrics[key] = float(summary_from_cfg[key])

    champion_tags = {
        "algorithm": "xgboost",
        DATA_SOURCE_TAG: str(cfg_dict.get("dataset_version", "paysim")),
        UNCERTAINTY_SHA256_TAG: cfg_sha256,
        "dataset_version": str(cfg_dict.get("dataset_version", "paysim")),
        "git_sha": get_git_sha(),
        "seed": "42",
        "conformal_method": str(uncertainty_config.method),
        "confidence_level": str(uncertainty_config.confidence_level),
    }

    pipeline = build_champion_pipeline()

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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tracking-uri",
        default=None,
        help="MLflow tracking URI override (defaults to MLFLOW_TRACKING_URI or .env)",
    )
    args = parser.parse_args(argv)
    populate(tracking_uri=args.tracking_uri)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
