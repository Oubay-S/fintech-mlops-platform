"""Run the Phase 4 model benchmark (Role 4).

Primary population: app-valid, in-scope — the traffic the app can actually
create. The runner is deliberately config-driven so the same code produces:

- contract-protocol results (the served model);
- per-fold metrics: ROC-AUC, PR-AUC, F1, precision, recall, MCC, Brier;
- the rule-negative hard subset;
- the serving-consistent balance variant;
- the deterministic rule baseline on the full population.

Examples (from the repository root):

    python -m ml.training.scripts.build_populations
    python -m ml.training.scripts.run_benchmark --models lr --folds 2 --seeds 42 --sample 20000
    python -m ml.training.scripts.run_benchmark --models lr,rf,xgb --population app_valid
    python -m ml.training.scripts.run_benchmark --quick --models lr  # 2 folds, 1 seed
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from sklearn.model_selection import StratifiedKFold, train_test_split
from sklearn.pipeline import Pipeline

from ml.common.paths import ML_DIR, REPO_ROOT
from ml.common.preprocessing import build_features, build_preprocessor, build_target
from ml.common.schema import TARGET
from ml.training.evaluation.metrics import fmt_metric, metrics_at, rule_baseline

DEFAULT_CONFIG = ML_DIR / "training" / "configs" / "benchmark.yaml"
RESULTS_DIR = ML_DIR / "training" / "results"
DOCS_DIR = ML_DIR / "training" / "docs"

# Contract = all numeric features; restricted = no new balances/zero/equality
# flags; rule_blind = also drop sender_old_balance and the drain ratio, so the
# deterministic equality rule cannot be reconstructed.
PROTOCOLS = {
    "contract": None,
    "restricted": [
        "amount",
        "sender_old_balance",
        "receiver_old_balance",
        "receiver_gain_ratio",
    ],
    "rule_blind": [
        "amount",
        "receiver_old_balance",
        "receiver_new_balance",
        "receiver_gain_ratio",
    ],
}


def resolve(path: str | Path) -> Path:
    path = Path(path)
    return path if path.is_absolute() else REPO_ROOT / path


def load_population(path: Path) -> pd.DataFrame:
    df = pd.read_parquet(path)
    df["type"] = df["type"].astype("category")
    return df.reset_index(drop=True)


def stratified_sample(df: pd.DataFrame, n: int | None, seed: int) -> pd.DataFrame:
    if n is None or len(df) <= n:
        return df.reset_index(drop=True)
    sample, _ = train_test_split(
        df, train_size=n, stratify=df[TARGET], random_state=seed
    )
    return sample.reset_index(drop=True)


def make_model(name: str, spec: dict, y_train: np.ndarray, seed: int):
    params = dict(spec.get("params", {}))
    if name == "lr":
        from sklearn.linear_model import LogisticRegression

        return LogisticRegression(**params, random_state=seed)
    if name == "rf":
        from sklearn.ensemble import RandomForestClassifier

        return RandomForestClassifier(**params, random_state=seed)
    if name == "xgb":
        from xgboost import XGBClassifier

        spw = spec.get("scale_pos_weight", "auto")
        if spw == "auto":
            positives = int(y_train.sum())
            negatives = int(len(y_train) - positives)
            params["scale_pos_weight"] = negatives / positives if positives else 1.0
        elif spw is not None:
            params["scale_pos_weight"] = spw
        return XGBClassifier(**params, random_state=seed)
    if name == "svm":
        from sklearn.calibration import CalibratedClassifierCV
        from sklearn.svm import LinearSVC

        base = LinearSVC(**params, random_state=seed)
        if spec.get("calibrate", True):
            return CalibratedClassifierCV(base, cv=3, method="sigmoid")
        return base
    if name == "mlp":
        from sklearn.neural_network import MLPClassifier

        return MLPClassifier(**params, random_state=seed)
    raise ValueError(f"Unknown model: {name}")


def run_fold(
    population: str,
    df: pd.DataFrame,
    model_name: str,
    model_spec: dict,
    *,
    protocol: str,
    folds: int,
    fold: int,
    seed: int,
    serving_consistent: bool,
) -> dict:
    splitter = StratifiedKFold(n_splits=folds, shuffle=True, random_state=seed)
    train_idx, test_idx = list(splitter.split(df, df[TARGET]))[fold]
    train_df = df.iloc[train_idx].reset_index(drop=True)
    test_df = df.iloc[test_idx].reset_index(drop=True)

    max_train_rows = model_spec.get("max_train_rows")
    train_df = stratified_sample(train_df, max_train_rows, seed)

    x_train = build_features(train_df)
    y_train = build_target(train_df).to_numpy()
    x_test = build_features(test_df)
    y_test = build_target(test_df).to_numpy()

    model = make_model(model_name, model_spec, y_train, seed)
    pipeline = Pipeline(
        [("prep", build_preprocessor(PROTOCOLS[protocol])), ("clf", model)]
    )

    start = time.perf_counter()
    pipeline.fit(x_train, y_train)
    train_seconds = time.perf_counter() - start

    start = time.perf_counter()
    probs = pipeline.predict_proba(x_test)[:, 1]
    predict_seconds = time.perf_counter() - start

    metrics = metrics_at(y_test, probs)
    confusion = metrics.pop("confusion_matrix")
    row = {
        "population": population,
        "model": model_name,
        "protocol": protocol,
        "fold": fold,
        "seed": seed,
        "n_train": int(len(train_df)),
        "n_test": int(len(test_df)),
        "n_features": int(len(pipeline.named_steps["prep"].get_feature_names_out())),
        "train_seconds": float(train_seconds),
        "predict_ms_per_row": float(predict_seconds / len(test_df) * 1000),
        **{f"cm_{key}": value for key, value in confusion.items()},
        **{key: value for key, value in metrics.items() if key != "threshold"},
        "threshold": float(metrics["threshold"]),
    }

    # Rule-negative hard subset (the frauds the deterministic rule misses).
    hard_mask = (test_df["amount"] == test_df["oldbalanceOrg"]).to_numpy()
    hard = metrics_at(y_test[hard_mask], probs[hard_mask])
    row.update(
        {
            "hard_rows": int(hard_mask.sum()),
            "hard_frauds": int(y_test[hard_mask].sum()),
            "hard_recall": hard["recall"],
            "hard_precision": hard["precision"],
            "hard_f1": hard["f1"],
            "hard_roc_auc": hard["roc_auc"],
        }
    )

    # The app computes both new balances; evaluate that view on app-valid rows.
    if serving_consistent:
        consistent = test_df.copy()
        consistent["newbalanceOrig"] = consistent["oldbalanceOrg"] - consistent["amount"]
        consistent["newbalanceDest"] = consistent["oldbalanceDest"] + consistent["amount"]
        valid_mask = (
            (consistent["amount"] > 0)
            & (consistent["amount"] <= consistent["oldbalanceOrg"])
        ).to_numpy()
        probs_consistent = pipeline.predict_proba(build_features(consistent))[:, 1]
        consistent_metrics = metrics_at(y_test[valid_mask], probs_consistent[valid_mask])
        hard_valid = hard_mask & valid_mask
        hard_consistent = metrics_at(y_test[hard_valid], probs_consistent[hard_valid])
        row.update(
            {
                "consistent_rows": int(valid_mask.sum()),
                "consistent_frauds": int(y_test[valid_mask].sum()),
                "consistent_recall": consistent_metrics["recall"],
                "consistent_precision": consistent_metrics["precision"],
                "consistent_f1": consistent_metrics["f1"],
                "consistent_hard_recall": hard_consistent["recall"],
                "consistent_hard_f1": hard_consistent["f1"],
            }
        )

    return row


def population_summary(population: str, df: pd.DataFrame) -> dict:
    rule = rule_baseline(df)
    return {
        "population": population,
        "rows": int(len(df)),
        "frauds": int(df[TARGET].sum()),
        "fraud_rate": float(df[TARGET].mean()),
        "rule": rule,
    }


def write_report(
    results: pd.DataFrame,
    populations: list[dict],
    path: Path,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Phase 4 Benchmark — Role 4",
        "",
        "Generated by `ml/training/scripts/run_benchmark.py` from `ml/training/configs/benchmark.yaml`.",
        "The primary population is **app-valid, in-scope** (the traffic the app can create);",
        "all-types/in-scope 1M samples are secondary. The headline score is dominated by the",
        "deterministic drain rule; the hard subset is the model test.",
        "",
        "## Populations",
        "",
        "| Population | Rows | Frauds | Fraud rate | Rule precision | Rule recall |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for pop in populations:
        rule = pop["rule"]
        lines.append(
            f"| {pop['population']} | {pop['rows']:,} | {pop['frauds']:,} | "
            f"{pop['fraud_rate']*100:.3f}% | {rule['precision']:.4f} | {rule['recall']:.4f} |"
        )

    metric_columns = [
        ("pr_auc", "PR-AUC"),
        ("roc_auc", "ROC-AUC"),
        ("recall", "Recall"),
        ("precision", "Precision"),
        ("f1", "F1"),
        ("hard_recall", "Hard recall"),
        ("consistent_hard_recall", "Consistent hard recall"),
        ("train_seconds", "Train s"),
        ("predict_ms_per_row", "ms/row"),
    ]
    for (population, protocol), subset in results.groupby(
        ["population", "protocol"], sort=False
    ):
        lines += [
            "",
            f"## {population} / {protocol} — mean ± std over folds/seeds",
            "",
            "| Model | Runs | " + " | ".join(label for _, label in metric_columns) + " |",
            "|---|---:|" + "|".join(["---:"] * len(metric_columns)) + "|",
        ]
        for model in sorted(subset["model"].unique()):
            model_rows = subset[subset["model"] == model]
            cells = [f"{len(model_rows)}"]
            for column, _ in metric_columns:
                values = pd.to_numeric(model_rows[column], errors="coerce").dropna()
                if values.empty:
                    cells.append("n/a")
                else:
                    cells.append(f"{values.mean():.4f} ± {values.std():.4f}")
            lines.append(f"| {model} | " + " | ".join(cells) + " |")

    lines += [
        "",
        "## Notes",
        "",
        "- `hard_recall` is measured on the rule-negative rows only; it is the number that matters.",
        "- **Ceiling effect:** the app-valid population is dominated by the drain rule; the fast models",
        "  are near-perfect and the differences are within noise. The all-serving/in-scope samples are",
        "  the sensitivity where model differences are more visible.",
        "- `consistent_hard_recall` recomputes `new = old ± amount` as the app does.",
        "- The app-valid population is a **biased proxy** for serving: `amount <= sender_old_balance`",
        "  removes most legitimate PaySim rows because PaySim's balances are inconsistent.",
        "  Report the all-serving/in-scope samples as a sensitivity; do not present the app-valid",
        "  rate as a real-world prior.",
        "- The rule baseline is deterministic; its full-population precision/recall are above.",
        "- SVM is a linear SVM with sigmoid calibration, capped at 50k training rows;",
        "  test folds are not subsampled. RBF SVC on 50k × 15 fits is too slow for the benchmark.",
        "",
    ]
    path.write_text("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--population", default=None, help="comma-separated population names")
    parser.add_argument("--protocol", choices=sorted(PROTOCOLS), default="contract")
    parser.add_argument("--models", default=None, help="comma-separated model names")
    parser.add_argument("--folds", type=int, default=None)
    parser.add_argument("--seeds", default=None, help="comma-separated seeds")
    parser.add_argument("--sample", type=int, default=None, help="stratified sample per population")
    parser.add_argument("--quick", action="store_true", help="2 folds, 1 seed")
    parser.add_argument("--output", default=None)
    parser.add_argument("--report", default=None)
    parser.add_argument(
        "--append",
        action="store_true",
        help="append to an existing results CSV (dedupe by population/model/protocol/fold/seed)",
    )
    args = parser.parse_args()

    config = yaml.safe_load(Path(args.config).read_text())
    folds = args.folds or config["cv"]["folds"]
    seeds = (
        [int(value) for value in args.seeds.split(",")]
        if args.seeds
        else [int(value) for value in config["cv"]["seeds"]]
    )
    if args.quick:
        folds, seeds = 2, [seeds[0]]

    model_names = (
        [value.strip() for value in args.models.split(",")]
        if args.models
        else list(config["models"].keys())
    )
    population_names = (
        [value.strip() for value in args.population.split(",")]
        if args.population
        else [config["populations"]["primary"]]
    )

    results: list[dict] = []
    population_summaries: list[dict] = []
    for population in population_names:
        path = resolve(config["populations"]["paths"][population])
        if not path.exists():
            raise FileNotFoundError(
                f"{path} not found. Run `python -m ml.training.scripts.build_populations` first."
            )
        df = stratified_sample(load_population(path), args.sample, config["seed"])
        population_summaries.append(population_summary(population, df))
        print(f"\n=== {population} / {args.protocol}: {len(df):,} rows, "
              f"{int(df[TARGET].sum()):,} frauds ({df[TARGET].mean()*100:.3f}%) ===")

        for model_name in model_names:
            model_spec = config["models"][model_name]
            for seed in seeds:
                for fold in range(folds):
                    row = run_fold(
                        population,
                        df,
                        model_name,
                        model_spec,
                        protocol=args.protocol,
                        folds=folds,
                        fold=fold,
                        seed=seed,
                        serving_consistent=bool(
                            config.get("evaluation", {}).get("serving_consistent", True)
                        ),
                    )
                    results.append(row)
                    print(
                        f"{model_name:>3} fold={fold} seed={seed} "
                        f"PR={fmt_metric(row['pr_auc'])} F1={row['f1']:.4f} "
                        f"hard={row['hard_recall']:.4f} "
                        f"train={row['train_seconds']:.1f}s"
                    )

    results_frame = pd.DataFrame(results)
    output_path = resolve(args.output or config["output"]["results_csv"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if args.append and output_path.exists():
        existing = pd.read_csv(output_path)
        results_frame = pd.concat([existing, results_frame], ignore_index=True)
        results_frame = results_frame.drop_duplicates(
            subset=["population", "model", "protocol", "fold", "seed"], keep="last"
        )
    results_frame.to_csv(output_path, index=False)

    report_path = resolve(args.report or config["output"]["report_md"])
    write_report(results_frame, population_summaries, report_path)

    summary_path = output_path.with_suffix(".populations.json")
    summary_path.write_text(json.dumps(population_summaries, indent=2))

    print(f"\nResults: {output_path}")
    print(f"Report:  {report_path}")
    print(f"Pops:    {summary_path}")


if __name__ == "__main__":
    main()
