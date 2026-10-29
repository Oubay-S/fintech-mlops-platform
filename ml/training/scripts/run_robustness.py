"""Temporal and destination-disjoint robustness evaluation (Role 4).

The app-valid random benchmark is the primary protocol. This script adds the
two splits V2.2 §24.2 asks for:

- **Temporal:** train on earlier `step`s, test on later `step`s (no hour
  overlap). Quantifies the drift; the fraud rate rises sharply late in PaySim.
- **Destination-disjoint:** group split by `nameDest`; test on unseen receivers.
  Sender-disjoint is trivial on PaySim (99.85% of senders appear once), so the
  destination is the meaningful generalization check.

For each split the XGBoost contract model is trained on serving-consistent
balances, calibrated with Mondrian split conformal at 99%, and evaluated with
the R1–R6 policy at the V2.2 provisional R5 = 500,000.

Run from the repository root:

    python -m ml.training.scripts.run_robustness
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
import yaml
from sklearn.model_selection import GroupShuffleSplit, train_test_split
from sklearn.pipeline import Pipeline

from ml.common.artifact_contract import UncertaintyConfig, prediction_set
from ml.common.paths import ML_DIR, REPO_ROOT
from ml.common.preprocessing import (
    build_features,
    build_preprocessor,
    build_target,
    stratified_split,
    temporal_split,
)
from ml.common.schema import TARGET
from ml.training.evaluation.metrics import fmt_metric, metrics_at, rule_baseline
from ml.training.scripts.run_benchmark import make_model
from ml.training.scripts.run_conformal import (
    app_valid,
    coverage_mix,
    decision_mix,
    mondrian_qhat,
    serving_consistent,
)

DEFAULT_POPULATION = ML_DIR / "data" / "processed" / "populations" / "app_valid.parquet"
DEFAULT_CONFIG = ML_DIR / "training" / "configs" / "benchmark.yaml"
DEFAULT_REPORT = ML_DIR / "training" / "docs" / "robustness_report.md"
DEFAULT_METRICS = ML_DIR / "training" / "results" / "robustness_metrics.json"
R5 = 500_000.0
CONFIDENCE = 0.99


def resolve(path: str | Path) -> Path:
    path = Path(path)
    return path if path.is_absolute() else REPO_ROOT / path


def destination_split(df: pd.DataFrame, test_size: float = 0.2, seed: int = 42):
    splitter = GroupShuffleSplit(n_splits=1, test_size=test_size, random_state=seed)
    train_idx, test_idx = next(splitter.split(df, groups=df["nameDest"]))
    return (
        df.iloc[train_idx].reset_index(drop=True),
        df.iloc[test_idx].reset_index(drop=True),
    )


def evaluate(
    name: str,
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
    benchmark: dict,
    *,
    seed: int = 42,
    extra: dict | None = None,
) -> dict:
    fit_df, cal_df = train_test_split(
        train_df, test_size=0.2, stratify=train_df[TARGET], random_state=seed
    )
    fit_df = serving_consistent(fit_df)
    cal_df = serving_consistent(cal_df)
    test_df = serving_consistent(test_df)

    x_fit = build_features(fit_df)
    y_fit = build_target(fit_df).to_numpy()
    x_cal = build_features(cal_df)
    y_cal = build_target(cal_df).to_numpy()
    x_test = build_features(test_df)
    y_test = build_target(test_df).to_numpy()
    amounts = test_df["amount"].to_numpy()

    model = make_model("xgb", benchmark["models"]["xgb"], y_fit, seed)
    pipeline = Pipeline([("prep", build_preprocessor()), ("clf", model)])
    pipeline.fit(x_fit, y_fit)
    p_cal = pipeline.predict_proba(x_cal)[:, 1]
    p_test = pipeline.predict_proba(x_test)[:, 1]

    alpha = 1.0 - CONFIDENCE
    q_fraud = mondrian_qhat(1.0 - p_cal[y_cal == 1], alpha)
    q_legit = mondrian_qhat(p_cal[y_cal == 0], alpha)
    config = UncertaintyConfig(
        confidence_level=CONFIDENCE,
        q_hat_fraud=q_fraud,
        q_hat_legit=q_legit,
        target_review_rate=0.05,
        method="mondrian_conformal",
        algorithm=type(model).__name__,
        model_feature_names=[
            str(name) for name in pipeline.named_steps["prep"].get_feature_names_out()
        ],
        calibration_rows=int(len(cal_df)),
        calibration_frauds=int(y_cal.sum()),
        eval_population=f"{name} (serving-consistent)",
        feature_list_version="1.2",
    )
    sets = [tuple(prediction_set(float(p), config)) for p in p_test]
    coverage = coverage_mix(y_test, sets)
    mix = decision_mix(y_test, sets, amounts, R5)
    test_metrics = metrics_at(y_test, p_test)
    rule_mask = (test_df["amount"] == test_df["oldbalanceOrg"]).to_numpy()
    hard_mask = ~rule_mask
    hard = metrics_at(y_test[hard_mask], p_test[hard_mask])
    rule = rule_baseline(test_df)

    result = {
        "split": name,
        "train_rows": int(len(train_df)),
        "train_frauds": int(train_df[TARGET].sum()),
        "train_rate": float(train_df[TARGET].mean()),
        "test_rows": int(len(test_df)),
        "test_frauds": int(y_test.sum()),
        "test_rate": float(y_test.mean()),
        "fit_rows": int(len(fit_df)),
        "calibration_rows": int(len(cal_df)),
        "q_hat_fraud": q_fraud,
        "q_hat_legit": q_legit,
        "coverage": coverage,
        "metrics": test_metrics,
        "hard": {"rows": int(hard_mask.sum()), "frauds": int(y_test[hard_mask].sum()), **hard},
        "rule": rule,
        "decision_mix": mix,
    }
    if extra:
        result.update(extra)
    return result


def write_report(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Temporal + Destination-Disjoint Robustness — Role 4",
        "",
        "**Model:** XGBoost, contract protocol, serving-consistent balances  ",
        f"**Conformal:** Mondrian {CONFIDENCE:.0%}; **R5:** {R5:,.0f} (V2.2 provisional)",
        "",
        "## Splits",
        "",
        "| Split | Train rows | Train fraud rate | Test rows | Test fraud rate | Notes |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        note = ""
        if "train_steps" in row:
            note = f"steps {row['train_steps'][0]}–{row['train_steps'][1]} → {row['test_steps'][0]}–{row['test_steps'][1]}"
        if "destination_overlap" in row:
            note = (
                f"{row['train_destinations']:,} train / {row['test_destinations']:,} test destinations; "
                f"overlap {row['destination_overlap']}"
            )
        lines.append(
            f"| {row['split']} | {row['train_rows']:,} | {row['train_rate']*100:.3f}% | "
            f"{row['test_rows']:,} | {row['test_rate']*100:.3f}% | {note} |"
        )

    lines += [
        "",
        "## Test metrics",
        "",
        "| Split | ROC-AUC | PR-AUC | F1 | Precision | Recall | Hard recall | Rule recall | Coverage legit | Coverage fraud | Review % | Missed frauds |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        metrics = row["metrics"]
        coverage = row["coverage"]
        mix = row["decision_mix"]
        lines.append(
            f"| {row['split']} | {fmt_metric(metrics['roc_auc'])} | {fmt_metric(metrics['pr_auc'])} | "
            f"{metrics['f1']:.4f} | {metrics['precision']:.4f} | {metrics['recall']:.4f} | "
            f"{row['hard']['recall']:.4f} | {row['rule']['recall']:.4f} | "
            f"{coverage['coverage_legit']*100:.2f}% | {coverage['coverage_fraud']*100:.2f}% | "
            f"{mix['review_pct']:.3f}% | {mix['frauds_R6_missed']} |"
        )

    lines += [
        "",
        "## R1–R6 decision mix (R5 = 500,000)",
        "",
        "| Split | R3 rejected | R4 model-uncertain | R5 amount-high | R6 approved | Review | Model-driven | Rule-driven | Frauds caught / missed | Legit in R3 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        mix = row["decision_mix"]
        lines.append(
            f"| {row['split']} | {mix['R3_pct']:.3f}% | {mix['R4_pct']:.3f}% | "
            f"{mix['R5_pct']:.3f}% | {mix['R6_pct']:.3f}% | **{mix['review_pct']:.3f}%** | "
            f"{mix['model_driven_pct']:.3f}% | {mix['rule_driven_pct']:.3f}% | "
            f"{mix['frauds_R3'] + mix['frauds_R4'] + mix['frauds_R5']}/{mix['frauds']} "
            f"(missed {mix['frauds_R6_missed']}) | {mix['legit_R3']} |"
        )

    lines += [
        "",
        "## Notes",
        "",
        "- **Temporal** is the drift check: later PaySim steps have a much higher fraud rate and lower volume.",
        "- **Destination-disjoint** is the generalization check: the test receivers are unseen; sender-disjoint",
        "  is trivial on PaySim (99.85% of senders appear once).",
        "- The app-valid filter (`amount <= sender_old_balance`) is a biased serving proxy; the primary",
        "  random split is in `conformal_decision_report.md`.",
        "- The app-valid hard subset is small (~31 frauds per test); treat hard-recall differences as noisy.",
        "- R5 500,000 is rule-driven; the review rate can move under drift even if the model is stable.",
        "",
    ]
    path.write_text("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--population", default=str(DEFAULT_POPULATION))
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--metrics", default=str(DEFAULT_METRICS))
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    df = pd.read_parquet(resolve(args.population))
    df["type"] = df["type"].astype("category")
    df = app_valid(df)
    benchmark = yaml.safe_load(Path(args.config).read_text())

    primary_train, primary_test = stratified_split(df, test_frac=0.2, random_state=args.seed)
    temporal_train, temporal_test = temporal_split(df, test_frac=0.2, time_col="step")
    destination_train, destination_test = destination_split(df, seed=args.seed)

    rows = [
        evaluate("primary_random", primary_train, primary_test, benchmark, seed=args.seed),
        evaluate(
            "temporal",
            temporal_train,
            temporal_test,
            benchmark,
            seed=args.seed,
            extra={
                "train_steps": [int(temporal_train["step"].min()), int(temporal_train["step"].max())],
                "test_steps": [int(temporal_test["step"].min()), int(temporal_test["step"].max())],
            },
        ),
        evaluate(
            "destination_disjoint",
            destination_train,
            destination_test,
            benchmark,
            seed=args.seed,
            extra={
                "train_destinations": int(destination_train["nameDest"].nunique()),
                "test_destinations": int(destination_test["nameDest"].nunique()),
                "destination_overlap": int(
                    len(set(destination_train["nameDest"]) & set(destination_test["nameDest"]))
                ),
            },
        ),
    ]

    metrics_path = resolve(args.metrics)
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.write_text(json.dumps(rows, indent=2, default=str))
    report_path = resolve(args.report)
    write_report(rows, report_path)

    for row in rows:
        mix = row["decision_mix"]
        print(
            f"{row['split']:>22}: test={row['test_rows']:,} frauds={row['test_frauds']:,} "
            f"PR={fmt_metric(row['metrics']['pr_auc'])} hard={row['hard']['recall']:.4f} "
            f"review={mix['review_pct']:.3f}% missed={mix['frauds_R6_missed']}"
        )
    print(f"\nReport:  {report_path}")
    print(f"Metrics: {metrics_path}")


if __name__ == "__main__":
    main()
