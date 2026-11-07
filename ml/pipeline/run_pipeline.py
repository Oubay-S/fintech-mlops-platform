"""Reproducible End-to-End MLOps Pipeline Orchestrator for CI & Academic Verification (Role 5).

Usage:
    # Nominal mode on PaySim CSV dataset (tags data_source=paysim, computes real benchmark stats, gates & promotes to @staging)
    python -m ml.pipeline.run_pipeline --data-path data/paysim.csv

    # CI / Smoke-test mode on in-memory synthetic dataset (tags data_source=synthetic, smoke-only, no gate/promotion)
    python -m ml.pipeline.run_pipeline --synthetic [--synthetic-rows 600]

Strict Governance & Boundaries:
    1. Zero silent fallback: If `--data-path` is missing or does not exist on disk and
       `--synthetic` is NOT explicitly passed, exits immediately with code 2 (EXIT_INFRA_ERROR).
    2. Every `--synthetic` run is explicitly smoke-only: it is tagged with `data_source=synthetic`,
       never logs fabricated or borrowed statistical validation artifacts, and never runs the
       promotion gate or promotes to `@staging` / `@production`.
    3. On real `--data-path` runs (`data_source=paysim`), paired statistical validation is
       computed directly from `ml/training/results/benchmark_runs.csv`, `validate_gate.py` is
       executed, and a passing candidate is promoted ONLY to `@staging` (never `@production`).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    f1_score,
    matthews_corrcoef,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline

from ml.common.artifact_contract import (
    CANDIDATE_ALIAS,
    DATA_SOURCE_TAG,
    EXPECTED_TRANSFORMED_FEATURES,
    MODEL_ARTIFACT_PATH,
    STATISTICAL_VALIDATION_ARTIFACT,
    UNCERTAINTY_CONFIG_ARTIFACT,
    UNCERTAINTY_SHA256_TAG,
    UncertaintyConfigContract,
)
from ml.common.preprocessing import (
    build_features,
    build_preprocessor,
    build_target,
    stratified_split,
    train_calibration_split,
)
from ml.common.schema import CONTRACT_FEATURES, DERIVED_FEATURES, assert_paysim_schema
from ml.training.scripts.run_statistics import (
    EXPECTED_BLOCKS,
    EXPECTED_PROTOCOLS,
    MODEL_ORDER,
    analyse,
    validate_benchmark,
)

from .conformal_eval import evaluate_existing_thresholds_on_split
from .mlflow_config import (
    EXIT_GATE_FAILURE,
    EXIT_INFRA_ERROR,
    EXIT_SUCCESS,
    REPO_ROOT,
    STAGING_ALIAS,
    GateThresholds,
    PipelineGateError,
    PipelineInfraError,
    get_git_sha,
    load_gate_thresholds,
    resolve_tracking_uri,
)
from .promote_model import promote_model
from .validate_gate import evaluate_run_against_gate

IN_SCOPE_TYPES = ("TRANSFER", "CASH_OUT")
BENCHMARK_RESULTS_CSV_PATH = (
    REPO_ROOT / "ml" / "training" / "results" / "benchmark_runs.csv"
)
STATISTICAL_METRICS: list[str] = [
    "pr_auc",
    "hard_recall",
    "consistent_hard_recall",
    "f1",
]


def _compute_real_statistical_validation(
    results_csv_path: Path = BENCHMARK_RESULTS_CSV_PATH,
) -> dict[str, Any]:
    """Compute genuine paired Friedman and Holm-adjusted Wilcoxon statistics from benchmark CSV.

    Raises `PipelineInfraError` if the benchmark CSV is missing, incomplete, or invalid.
    Never fabricates or falls back to placeholder statistical values.
    """
    if not results_csv_path.exists():
        raise PipelineInfraError(
            f"Benchmark results CSV not found at '{results_csv_path}'. "
            "Cannot compute statistical validation without real benchmark runs."
        )
    try:
        results_df = pd.read_csv(results_csv_path)
        validate_benchmark(
            results_df,
            expected_models=MODEL_ORDER,
            expected_protocols=EXPECTED_PROTOCOLS,
            expected_blocks=EXPECTED_BLOCKS,
            allow_partial=False,
        )
        findings = analyse(results_df, STATISTICAL_METRICS)
    except Exception as exc:
        raise PipelineInfraError(
            f"Failed to compute valid paired statistical validation from '{results_csv_path}': {exc}"
        ) from exc

    if not findings:
        raise PipelineInfraError(
            f"No paired statistical findings produced from '{results_csv_path}'."
        )

    try:
        results_label = results_csv_path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        results_label = results_csv_path.name

    return {
        "schema_version": "1.0",
        "results_csv": results_label,
        "metrics": list(STATISTICAL_METRICS),
        "findings": findings,
    }


def generate_synthetic_paysim_df(n_rows: int = 600, seed: int = 42) -> pd.DataFrame:
    """Generate a deterministic, separable in-scope PaySim DataFrame for CI testing."""
    if n_rows < 100:
        raise PipelineInfraError(
            "--synthetic-rows must be >= 100 for stratified splits."
        )

    rng = np.random.default_rng(seed)
    n_fraud = max(int(n_rows * 0.15), 20)
    n_legit = n_rows - n_fraud

    # Legitimate partial transfers / cash-outs (sender retains balance after transaction)
    legit_types = rng.choice(IN_SCOPE_TYPES, size=n_legit)
    legit_amounts = rng.uniform(50.0, 25000.0, size=n_legit).round(2)
    legit_old_orig = (legit_amounts + rng.uniform(500.0, 80000.0, size=n_legit)).round(
        2
    )
    legit_new_orig = (legit_old_orig - legit_amounts).round(2)
    legit_old_dest = rng.uniform(0.0, 150000.0, size=n_legit).round(2)
    legit_new_dest = (legit_old_dest + legit_amounts).round(2)

    # Fraudulent full-drain transfers / cash-outs (amount == oldbalanceOrg, newbalanceOrig == 0)
    fraud_types = rng.choice(IN_SCOPE_TYPES, size=n_fraud)
    fraud_amounts = rng.uniform(15000.0, 450000.0, size=n_fraud).round(2)
    fraud_old_orig = fraud_amounts.copy()
    fraud_new_orig = np.zeros(n_fraud, dtype=float)
    fraud_old_dest = rng.uniform(0.0, 5000.0, size=n_fraud).round(2)
    fraud_new_dest = (fraud_old_dest + fraud_amounts).round(2)

    df = pd.DataFrame(
        {
            "step": rng.integers(1, 200, size=n_rows),
            "type": np.concatenate([legit_types, fraud_types]),
            "amount": np.concatenate([legit_amounts, fraud_amounts]),
            "nameOrig": [f"C{100000 + i}" for i in range(n_rows)],
            "oldbalanceOrg": np.concatenate([legit_old_orig, fraud_old_orig]),
            "newbalanceOrig": np.concatenate([legit_new_orig, fraud_new_orig]),
            "nameDest": [f"C{200000 + i}" for i in range(n_rows)],
            "oldbalanceDest": np.concatenate([legit_old_dest, fraud_old_dest]),
            "newbalanceDest": np.concatenate([legit_new_dest, fraud_new_dest]),
            "isFraud": np.concatenate(
                [np.zeros(n_legit, dtype=int), np.ones(n_fraud, dtype=int)]
            ),
            "isFlaggedFraud": np.zeros(n_rows, dtype=int),
        }
    )
    return df.sample(frac=1.0, random_state=seed).reset_index(drop=True)


def load_input_dataset(
    *,
    data_path: str | Path | None,
    synthetic: bool,
    synthetic_rows: int = 600,
    seed: int = 42,
) -> tuple[pd.DataFrame, str]:
    """Load PaySim CSV or generate synthetic CI data. Zero silent fallback."""
    if synthetic and data_path:
        raise PipelineInfraError(
            "Flags --data-path and --synthetic are mutually exclusive."
        )

    if synthetic:
        return generate_synthetic_paysim_df(
            n_rows=synthetic_rows, seed=seed
        ), "synthetic"

    if not data_path:
        raise PipelineInfraError(
            "Missing dataset input: provide --data-path <CSV> or explicitly pass --synthetic."
        )

    resolved_path = Path(data_path)
    if not resolved_path.exists() or not resolved_path.is_file():
        raise PipelineInfraError(
            f"Dataset CSV not found at '{resolved_path}'. Refusing silent fallback to synthetic."
        )

    try:
        df = pd.read_csv(resolved_path)
        assert_paysim_schema(df)
    except Exception as exc:
        raise PipelineInfraError(
            f"Failed to read valid PaySim CSV from '{resolved_path}': {exc}"
        ) from exc

    filtered = df[df["type"].isin(IN_SCOPE_TYPES)].reset_index(drop=True)
    if filtered.empty:
        raise PipelineInfraError(
            f"Dataset '{resolved_path}' contains 0 in-scope (TRANSFER/CASH_OUT) rows."
        )
    return filtered, "paysim"


def _measure_inference_p95_ms(
    pipeline: Pipeline, x_test: pd.DataFrame, n_samples: int = 50
) -> float:
    sample_count = min(len(x_test), n_samples)
    latencies_ms: list[float] = []
    # Warmup
    pipeline.predict_proba(x_test.iloc[[0]])
    for idx in range(sample_count):
        t0 = time.perf_counter_ns()
        pipeline.predict_proba(x_test.iloc[[idx]])
        latencies_ms.append((time.perf_counter_ns() - t0) / 1_000_000.0)
    return float(np.percentile(latencies_ms, 95))


def execute_pipeline(
    *,
    tracking_uri: str,
    data_path: str | Path | None = None,
    synthetic: bool = False,
    synthetic_rows: int = 600,
    seed: int = 42,
    confidence_level: float = 0.95,
    q_hat_fraud: float = 0.65,
    q_hat_legit: float = 0.65,
    thresholds: GateThresholds | None = None,
) -> dict[str, Any]:
    """Execute end-to-end pipeline: ingest -> fit -> evaluate -> log @candidate -> gate -> @staging."""
    cfg = thresholds or load_gate_thresholds()
    df, data_source = load_input_dataset(
        data_path=data_path,
        synthetic=synthetic,
        synthetic_rows=synthetic_rows,
        seed=seed,
    )

    try:
        import mlflow
        from mlflow.tracking import MlflowClient
    except ImportError as exc:
        raise PipelineInfraError(f"MLflow is not installed: {exc}") from exc

    train_df, test_df = stratified_split(df, test_frac=0.2, random_state=seed)
    fit_df, _cal_df = train_calibration_split(train_df, cal_frac=0.2, random_state=seed)

    x_fit = build_features(fit_df)
    y_fit = build_target(fit_df).to_numpy()
    x_test = build_features(test_df)
    y_test = build_target(test_df).to_numpy()

    classifier = LogisticRegression(C=5.0, max_iter=250, random_state=seed)
    pipeline = Pipeline(
        steps=[
            ("preprocessor", build_preprocessor()),
            ("classifier", classifier),
        ]
    )
    pipeline.fit(x_fit, y_fit)

    # Verify 14-column transformed signature
    names_out = [
        str(c) for c in pipeline.named_steps["preprocessor"].get_feature_names_out()
    ]
    if names_out != list(EXPECTED_TRANSFORMED_FEATURES):
        raise PipelineInfraError(
            f"Preprocessor output columns {names_out} != expected {EXPECTED_TRANSFORMED_FEATURES}"
        )

    p_test = pipeline.predict_proba(x_test)[:, 1]
    y_pred = (p_test >= 0.5).astype(int)

    roc_auc = float(roc_auc_score(y_test, p_test))
    pr_auc = float(average_precision_score(y_test, p_test))
    f1 = float(f1_score(y_test, y_pred, zero_division=0))
    precision = float(precision_score(y_test, y_pred, zero_division=0))
    recall = float(recall_score(y_test, y_pred, zero_division=0))
    mcc = float(matthews_corrcoef(y_test, y_pred))
    brier = float(brier_score_loss(y_test, p_test))
    p95_ms = _measure_inference_p95_ms(pipeline, x_test)

    # Evaluate pre-configured conformal thresholds on test split (no recalibration)
    provisional_config = UncertaintyConfigContract(
        method="mondrian_conformal",
        confidence_level=confidence_level,
        target_review_rate=cfg.max_expected_review_rate,
        q_hat_fraud=q_hat_fraud,
        q_hat_legit=q_hat_legit,
        algorithm=type(classifier).__name__,
        trained_at=datetime.now(UTC).isoformat(),
        feature_names=list(CONTRACT_FEATURES + DERIVED_FEATURES),
        transformed_feature_names=names_out,
    )
    conf_metrics = evaluate_existing_thresholds_on_split(
        p_fraud=p_test,
        y_true=y_test,
        config=provisional_config,
    )

    metrics_summary = {
        "roc_auc": roc_auc,
        "pr_auc": pr_auc,
        "f1": f1,
        "precision": precision,
        "recall": recall,
        "mcc": mcc,
        "brier_score": brier,
        "expected_review_rate": conf_metrics["expected_review_rate"],
        "model_uncertain_rate": conf_metrics["model_uncertain_rate"],
        "coverage_legit": conf_metrics["coverage_legit"],
        "coverage_fraud": conf_metrics["coverage_fraud"],
        "inference_p95_ms": p95_ms,
    }

    uncertainty_config = UncertaintyConfigContract(
        method="mondrian_conformal",
        confidence_level=confidence_level,
        target_review_rate=cfg.max_expected_review_rate,
        q_hat_fraud=q_hat_fraud,
        q_hat_legit=q_hat_legit,
        algorithm=type(classifier).__name__,
        trained_at=datetime.now(UTC).isoformat(),
        feature_names=list(CONTRACT_FEATURES + DERIVED_FEATURES),
        transformed_feature_names=names_out,
        metrics_summary=metrics_summary,
    )
    config_sha256 = uncertainty_config.sha256()

    # Compute genuine paired statistical validation ONLY for real PaySim runs (never for synthetic smoke runs)
    stat_payload: dict[str, Any] | None = (
        _compute_real_statistical_validation() if data_source == "paysim" else None
    )

    try:
        mlflow.set_tracking_uri(tracking_uri)
        client = MlflowClient(tracking_uri=tracking_uri)
        mlflow.set_experiment(cfg.experiment_name)

        with mlflow.start_run(run_name=f"pipeline-{data_source}-{seed}") as run:
            run_id = str(run.info.run_id)
            mlflow.set_tags(
                {
                    "algorithm": type(classifier).__name__,
                    "dataset_version": "paysim-v1",
                    "git_sha": get_git_sha(),
                    "seed": str(seed),
                    DATA_SOURCE_TAG: data_source,
                    UNCERTAINTY_SHA256_TAG: config_sha256,
                }
            )
            mlflow.log_params(
                {
                    "C": 5.0,
                    "max_iter": 250,
                    "seed": seed,
                    "confidence_level": confidence_level,
                    "data_source": data_source,
                }
            )
            mlflow.log_metrics(metrics_summary)
            mlflow.log_dict(uncertainty_config.to_dict(), UNCERTAINTY_CONFIG_ARTIFACT)
            if stat_payload is not None:
                mlflow.log_dict(stat_payload, STATISTICAL_VALIDATION_ARTIFACT)

            mlflow.sklearn.log_model(
                sk_model=pipeline,
                artifact_path=MODEL_ARTIFACT_PATH,
                registered_model_name=cfg.model_name,
                serialization_format="cloudpickle",
            )

        versions = client.search_model_versions(f"name='{cfg.model_name}'")
        candidate_version: str | None = None
        for v in versions:
            if str(v.run_id) == run_id:
                candidate_version = str(v.version)
                break
        if candidate_version is None:
            raise PipelineInfraError(
                f"Model '{cfg.model_name}' was logged for run '{run_id}' but no matching registered version was found."
            )

        client.set_registered_model_alias(
            name=cfg.model_name,
            alias=CANDIDATE_ALIAS,
            version=candidate_version,
        )
    except (PipelineGateError, PipelineInfraError):
        raise
    except Exception as exc:
        raise PipelineInfraError(
            f"Failed to log candidate run to MLflow: {exc}"
        ) from exc

    # Synthetic mode is strictly smoke-only: never evaluate the gate or promote to @staging / @production
    if data_source == "synthetic":
        return {
            "status": "SUCCESS",
            "exit_code": EXIT_SUCCESS,
            "run_id": run_id,
            "model_name": cfg.model_name,
            "model_version": candidate_version,
            "candidate_alias": CANDIDATE_ALIAS,
            "promoted_to_alias": None,
            "gate_evaluated": False,
            "data_source": data_source,
            "uncertainty_config_sha256": config_sha256,
            "metrics": metrics_summary,
        }

    # Run Quality Gate on @candidate (real PaySim runs only)
    gate_report = evaluate_run_against_gate(
        tracking_uri=tracking_uri,
        model_name=cfg.model_name,
        alias=CANDIDATE_ALIAS,
        thresholds=cfg,
    )
    if not gate_report.passed:
        raise PipelineGateError(
            f"Candidate run '{run_id}' failed Quality Gate: {'; '.join(gate_report.failures)}"
        )

    # Promote @candidate -> @staging (NEVER directly to @production)
    promo_report = promote_model(
        tracking_uri=tracking_uri,
        from_alias=CANDIDATE_ALIAS,
        to_alias=STAGING_ALIAS,
        model_name=cfg.model_name,
        thresholds=cfg,
    )

    return {
        "status": "SUCCESS",
        "exit_code": EXIT_SUCCESS,
        "run_id": run_id,
        "model_name": cfg.model_name,
        "model_version": promo_report.promoted_version,
        "candidate_alias": CANDIDATE_ALIAS,
        "promoted_to_alias": promo_report.to_alias,
        "gate_evaluated": True,
        "data_source": data_source,
        "uncertainty_config_sha256": config_sha256,
        "metrics": metrics_summary,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-path",
        default=None,
        help="Path to PaySim CSV dataset (required unless --synthetic is passed)",
    )
    parser.add_argument(
        "--synthetic",
        action="store_true",
        help="Generate synthetic in-memory dataset for CI / reproducibility check (tags data_source=synthetic)",
    )
    parser.add_argument(
        "--synthetic-rows",
        type=int,
        default=600,
        help="Number of synthetic rows when --synthetic is set (default: 600)",
    )
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument(
        "--tracking-uri", default=None, help="MLflow tracking URI override"
    )
    parser.add_argument(
        "--thresholds", default=None, help="Path to gate_thresholds.yaml"
    )
    args = parser.parse_args(argv)

    try:
        thresholds = load_gate_thresholds(args.thresholds)
        tracking_uri = resolve_tracking_uri(args.tracking_uri)
        summary = execute_pipeline(
            tracking_uri=tracking_uri,
            data_path=args.data_path,
            synthetic=args.synthetic,
            synthetic_rows=args.synthetic_rows,
            seed=args.seed,
            thresholds=thresholds,
        )
        print(json.dumps(summary, indent=2))
        return EXIT_SUCCESS
    except PipelineGateError as exc:
        print(
            json.dumps(
                {
                    "status": "GATE_FAILURE",
                    "exit_code": EXIT_GATE_FAILURE,
                    "error": str(exc),
                },
                indent=2,
            ),
            file=sys.stderr,
        )
        return EXIT_GATE_FAILURE
    except PipelineInfraError as exc:
        print(
            json.dumps(
                {
                    "status": "INFRA_ERROR",
                    "exit_code": EXIT_INFRA_ERROR,
                    "error": str(exc),
                },
                indent=2,
            ),
            file=sys.stderr,
        )
        return EXIT_INFRA_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
