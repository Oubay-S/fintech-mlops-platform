"""Logistic Regression baseline for the PaySim fraud model (Role 4).

Runs the primary stratified protocol:
  fit (train) -> preprocessor -> LogisticRegression -> test evaluation.

Outputs (under ml/training/docs/):
  - baseline_report.md
  - baseline_metrics.json
  - baseline_*.png (confusion matrix, ROC, PR, calibration, probability distribution)

Run from the repository root:

    python -m ml.training.scripts.run_baseline            # full data
    python -m ml.training.scripts.run_baseline --sample   # 200k sample
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import joblib
import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from sklearn.calibration import calibration_curve
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    matthews_corrcoef,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
    roc_curve,
)
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from ml.common.loading import load_paysim
from ml.common.paths import ML_DIR
from ml.common.preprocessing import (
    build_features,
    build_preprocessor,
    build_target,
    stratified_split,
    train_calibration_split,
)
from ml.common.schema import TARGET

DOCS_DIR = ML_DIR / "training" / "docs"
FIG_DIR = DOCS_DIR / "figures"
PROCESSED_DIR = ML_DIR / "data" / "processed"


def metrics_at(y_true: np.ndarray, probs: np.ndarray, threshold: float = 0.5) -> dict:
    predicted = (probs >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_true, predicted).ravel()
    return {
        "threshold": float(threshold),
        "accuracy": float(accuracy_score(y_true, predicted)),
        "precision": float(precision_score(y_true, predicted, zero_division=0)),
        "recall": float(recall_score(y_true, predicted, zero_division=0)),
        "f1": float(f1_score(y_true, predicted, zero_division=0)),
        "roc_auc": float(roc_auc_score(y_true, probs)),
        "pr_auc": float(average_precision_score(y_true, probs)),
        "mcc": float(matthews_corrcoef(y_true, predicted)),
        "brier": float(brier_score_loss(y_true, probs)),
        "predicted_positive_rate": float(predicted.mean()),
        "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
    }


def best_f1_threshold(y_true: np.ndarray, probs: np.ndarray) -> float:
    precision, recall, thresholds = precision_recall_curve(y_true, probs)
    f1 = 2 * precision * recall / (precision + recall + 1e-12)
    index = int(np.nanargmax(f1))
    if index >= len(thresholds):
        index = len(thresholds) - 1
    return float(thresholds[index])


def ablation_probe(features_fit, features_cal, features_test, y_fit, y_cal, y_test) -> dict:
    """Logistic-Regression-only preview of the Phase-4 restricted ablation."""
    feature_sets = {
        "full_contract": [
            "amount",
            "sender_old_balance",
            "sender_new_balance",
            "receiver_old_balance",
            "receiver_new_balance",
            "balance_drain_ratio",
            "receiver_gain_ratio",
            "sender_zero_after",
            "amount_equals_old_balance",
        ],
        "no_new_balances": [
            "amount",
            "sender_old_balance",
            "receiver_old_balance",
            "receiver_gain_ratio",
        ],
        "amount_only": ["amount"],
    }
    results = {}
    for name, numeric in feature_sets.items():
        preprocessor = ColumnTransformer(
            transformers=[
                ("num", StandardScaler(), numeric),
                (
                    "cat",
                    OneHotEncoder(handle_unknown="ignore", sparse_output=False),
                    ["type"],
                ),
            ],
            remainder="drop",
        )
        X_fit = preprocessor.fit_transform(features_fit[numeric + ["type"]])
        X_cal = preprocessor.transform(features_cal[numeric + ["type"]])
        X_test = preprocessor.transform(features_test[numeric + ["type"]])

        model = LogisticRegression(max_iter=1000, solver="lbfgs", random_state=42)
        model.fit(X_fit, y_fit)
        probs_cal = model.predict_proba(X_cal)[:, 1]
        probs_test = model.predict_proba(X_test)[:, 1]
        threshold = best_f1_threshold(y_cal, probs_cal)
        predicted = (probs_test >= threshold).astype(int)
        results[name] = {
            "roc_auc": float(roc_auc_score(y_test, probs_test)),
            "pr_auc": float(average_precision_score(y_test, probs_test)),
            "f1": float(f1_score(y_test, predicted, zero_division=0)),
            "recall": float(recall_score(y_test, predicted, zero_division=0)),
            "threshold": float(threshold),
            "n_features": len(numeric) + 5,
        }
    return results


def inference_timing(model, features: np.ndarray, *, n_single: int = 500) -> dict:
    subset = features[: min(len(features), 50_000)]
    start = time.perf_counter()
    model.predict_proba(subset)
    batch_seconds = time.perf_counter() - start

    rng = np.random.default_rng(42)
    indices = rng.choice(len(features), size=min(n_single, len(features)), replace=False)
    single = []
    for index in indices:
        start = time.perf_counter()
        model.predict_proba(features[index : index + 1])
        single.append((time.perf_counter() - start) * 1000)
    single = np.asarray(single)
    return {
        "batch_ms_per_row": float(batch_seconds / len(subset) * 1000),
        "single_p50_ms": float(np.percentile(single, 50)),
        "single_p95_ms": float(np.percentile(single, 95)),
        "single_n": int(len(single)),
    }


def save_figures(y_true, probs, threshold, suffix: str) -> list[str]:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    saved = []

    predicted = (probs >= threshold).astype(int)
    cm = confusion_matrix(y_true, predicted)
    fig, ax = plt.subplots(figsize=(4.5, 4))
    im = ax.imshow(cm, cmap="Blues")
    ax.set_title("Confusion matrix (threshold %.2f)" % threshold)
    ax.set_xlabel("predicted")
    ax.set_ylabel("actual")
    ax.set_xticks([0, 1], ["legit", "fraud"])
    ax.set_yticks([0, 1], ["legit", "fraud"])
    for i in range(2):
        for j in range(2):
            ax.text(j, i, f"{cm[i, j]:,}", ha="center", va="center", fontsize=10)
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    fig.tight_layout()
    path = FIG_DIR / f"baseline{suffix}_confusion_matrix.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    saved.append(path.name)

    fpr, tpr, _ = roc_curve(y_true, probs)
    fig, ax = plt.subplots(figsize=(5, 4))
    ax.plot(fpr, tpr, color="#4C78A8", label=f"ROC-AUC = {roc_auc_score(y_true, probs):.4f}")
    ax.plot([0, 1], [0, 1], linestyle="--", color="gray", linewidth=0.8)
    ax.set_xlabel("false positive rate")
    ax.set_ylabel("true positive rate")
    ax.set_title("ROC curve — baseline")
    ax.legend(loc="lower right")
    fig.tight_layout()
    path = FIG_DIR / f"baseline{suffix}_roc_curve.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    saved.append(path.name)

    precision, recall, _ = precision_recall_curve(y_true, probs)
    fig, ax = plt.subplots(figsize=(5, 4))
    ax.plot(recall, precision, color="#E45756", label=f"PR-AUC = {average_precision_score(y_true, probs):.4f}")
    ax.set_xlabel("recall")
    ax.set_ylabel("precision")
    ax.set_title("Precision-recall curve — baseline")
    ax.legend(loc="upper right")
    fig.tight_layout()
    path = FIG_DIR / f"baseline{suffix}_pr_curve.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    saved.append(path.name)

    fraction_positive, mean_predicted = calibration_curve(
        y_true, probs, n_bins=10, strategy="quantile"
    )
    fig, ax = plt.subplots(figsize=(5, 4))
    ax.plot(mean_predicted, fraction_positive, marker="o", color="#54A24B", label="model")
    ax.plot([0, 1], [0, 1], linestyle="--", color="gray", linewidth=0.8, label="perfect")
    ax.set_xlabel("mean predicted probability")
    ax.set_ylabel("observed fraud rate")
    ax.set_title("Calibration curve — baseline")
    ax.legend()
    fig.tight_layout()
    path = FIG_DIR / f"baseline{suffix}_calibration.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    saved.append(path.name)

    fig, ax = plt.subplots(figsize=(6, 4))
    for label, name, color in [(0, "legitimate", "#4C78A8"), (1, "fraud", "#E45756")]:
        values = probs[y_true == label]
        ax.hist(values, bins=50, alpha=0.55, label=name, color=color, log=True)
    ax.set_xlabel("predicted probability")
    ax.set_ylabel("transactions (log scale)")
    ax.set_title("Predicted probability by class — baseline")
    ax.legend()
    fig.tight_layout()
    path = FIG_DIR / f"baseline{suffix}_probability_distribution.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    saved.append(path.name)

    return saved


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", action="store_true", help="use the 200k sample")
    parser.add_argument("--max-iter", type=int, default=1000, help="LogisticRegression max_iter")
    parser.add_argument(
        "--ablation",
        action="store_true",
        help="also run the LR-only restricted ablation preview",
    )
    args = parser.parse_args()

    suffix = "_sample" if args.sample else ""
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    df = load_paysim(sample=args.sample)
    train_df, test_df = stratified_split(df, test_frac=0.2, random_state=42)
    fit_df, cal_df = train_calibration_split(train_df, cal_frac=0.2, random_state=42)

    features_fit = build_features(fit_df)
    features_cal = build_features(cal_df)
    features_test = build_features(test_df)
    y_fit = build_target(fit_df).to_numpy()
    y_cal = build_target(cal_df).to_numpy()
    y_test = build_target(test_df).to_numpy()

    preprocessor = build_preprocessor()
    X_fit = preprocessor.fit_transform(features_fit)
    X_cal = preprocessor.transform(features_cal)
    X_test = preprocessor.transform(features_test)

    model = LogisticRegression(max_iter=args.max_iter, solver="lbfgs", random_state=42)
    start = time.perf_counter()
    model.fit(X_fit, y_fit)
    train_seconds = time.perf_counter() - start

    probs_cal = model.predict_proba(X_cal)[:, 1]
    probs_test = model.predict_proba(X_test)[:, 1]

    calibration_threshold = best_f1_threshold(y_cal, probs_cal)
    metrics_05 = metrics_at(y_test, probs_test, threshold=0.5)
    metrics_cal = metrics_at(y_test, probs_test, threshold=calibration_threshold)
    timing = inference_timing(model, X_test)

    ablation = None
    if args.ablation:
        ablation = ablation_probe(
            features_fit, features_cal, features_test, y_fit, y_cal, y_test
        )

    majority_accuracy = float(1 - y_test.mean())
    results = {
        "dataset": "sample" if args.sample else "full",
        "rows": int(len(df)),
        "split": {
            "fit_rows": int(len(fit_df)),
            "calibration_rows": int(len(cal_df)),
            "test_rows": int(len(test_df)),
            "fit_fraud_rate": float(y_fit.mean()),
            "calibration_fraud_rate": float(y_cal.mean()),
            "test_fraud_rate": float(y_test.mean()),
        },
        "model": {
            "name": "LogisticRegression",
            "solver": "lbfgs",
            "max_iter": args.max_iter,
            "class_weight": None,
            "n_features": int(X_fit.shape[1]),
            "train_seconds": float(train_seconds),
        },
        "test_metrics_at_0.5": metrics_05,
        "test_metrics_at_calibration_threshold": metrics_cal,
        "calibration_threshold": calibration_threshold,
        "inference_timing": timing,
        "ablation_probe_lr": ablation,
        "majority_class_accuracy": majority_accuracy,
    }

    (DOCS_DIR / f"baseline_metrics{suffix}.json").write_text(json.dumps(results, indent=2))
    joblib.dump(
        {"preprocessor": preprocessor, "model": model},
        PROCESSED_DIR / f"baseline_model{suffix}.joblib",
    )

    figures = save_figures(y_test, probs_test, threshold=0.5, suffix=suffix)

    ablation_section = ""
    if ablation is not None:
        labels = {
            "full_contract": "Full contract",
            "no_new_balances": "No new balances",
            "amount_only": "Amount only",
        }
        rows = [
            "## Preliminary ablation (Logistic Regression only)",
            "",
            "| Feature set | Features | ROC-AUC | PR-AUC | F1 | Recall |",
            "|---|---|---|---|---|---|",
        ]
        for key in ["full_contract", "no_new_balances", "amount_only"]:
            result = ablation[key]
            rows.append(
                f"| {labels[key]} | {result['n_features']} | {result['roc_auc']:.4f} | "
                f"{result['pr_auc']:.4f} | {result['f1']:.4f} | {result['recall']:.4f} |"
            )
        rows.append("")
        rows.append(
            "The full contract model is near-perfect because the new-balance/equality "
            "features encode the simulator's drain rule; without them the task becomes "
            "genuinely hard. The Phase-4 benchmark will repeat this ablation for all five "
            "algorithms."
        )
        ablation_section = "\n".join(rows)

    report = f"""# Logistic Regression Baseline — {'sample' if args.sample else 'full data'}

**Generated:** {time.strftime('%Y-%m-%d')} · **Script:** `ml/training/scripts/run_baseline.py`
**Model:** LogisticRegression (lbfgs, max_iter={args.max_iter}, no class weights)
**Preprocessing:** shared `ml/common/preprocessing.py` (14 features: 9 scaled numeric + 5 one-hot `type`)

## Split (primary protocol)

| Split | Rows | Fraud rate |
|---|---|---|
| Fit | {len(fit_df):,} | {y_fit.mean()*100:.4f}% |
| Calibration | {len(cal_df):,} | {y_cal.mean()*100:.4f}% |
| Test | {len(test_df):,} | {y_test.mean()*100:.4f}% |

## Test metrics — threshold 0.5

| Metric | Value |
|---|---|
| Accuracy | {metrics_05['accuracy']:.4f} |
| Precision | {metrics_05['precision']:.4f} |
| Recall | {metrics_05['recall']:.4f} |
| F1 | {metrics_05['f1']:.4f} |
| ROC-AUC | {metrics_05['roc_auc']:.4f} |
| PR-AUC | {metrics_05['pr_auc']:.4f} |
| MCC | {metrics_05['mcc']:.4f} |
| Brier | {metrics_05['brier']:.6f} |
| Predicted positive rate | {metrics_05['predicted_positive_rate']*100:.3f}% |

Confusion matrix at 0.5: **TN {metrics_05['confusion_matrix']['tn']:,} · FP {metrics_05['confusion_matrix']['fp']:,} · FN {metrics_05['confusion_matrix']['fn']:,} · TP {metrics_05['confusion_matrix']['tp']:,}**

Reference — always predicting "legitimate" gives accuracy {majority_accuracy:.4f}, recall 0, F1 0: **accuracy alone is meaningless here**.

## Calibration-selected operating point

Best F1 threshold on the **calibration** set: **{calibration_threshold:.4f}**.

| Metric | Value |
|---|---|
| Precision | {metrics_cal['precision']:.4f} |
| Recall | {metrics_cal['recall']:.4f} |
| F1 | {metrics_cal['f1']:.4f} |
| MCC | {metrics_cal['mcc']:.4f} |

{ablation_section}

## Inference timing

| Measure | Value |
|---|---|
| Batch (amortised) | {timing['batch_ms_per_row']*1000:.3f} µs/row |
| Single row p50 | {timing['single_p50_ms']:.3f} ms |
| Single row p95 | {timing['single_p95_ms']:.3f} ms |

## Figures

![Confusion matrix](figures/baseline{suffix}_confusion_matrix.png)
![ROC curve](figures/baseline{suffix}_roc_curve.png)
![PR curve](figures/baseline{suffix}_pr_curve.png)
![Calibration curve](figures/baseline{suffix}_calibration.png)
![Probability distribution](figures/baseline{suffix}_probability_distribution.png)

## Interpretation

- PaySim's near-deterministic drain rule makes a linear baseline very strong; high scores are expected and are a **dataset property**, not evidence of real-world capability.
- The calibration curve and Brier score are reported as-is; class weighting/resampling is evaluated in the Phase 4 benchmark, not hidden in the baseline.
- The threshold 0.5 is arbitrary under 0.129% prevalence; the calibration-selected threshold above is a first honest operating point. The final policy (allow/decline/review) will use conformal prediction sets in Phase 6.
- Next: Phase 4 — five algorithms (LR, RF, XGBoost, SVM, MLP), repeated CV × seeds, plus the restricted ablation without new-balance fields.

## Artifacts

- `ml/training/docs/baseline_metrics{suffix}.json`
- `ml/data/processed/baseline_model{suffix}.joblib` (git-ignored)
- `ml/training/docs/figures/baseline{suffix}_*.png`
"""
    (DOCS_DIR / f"baseline_report{suffix}.md").write_text(report)

    print(json.dumps(results, indent=2))
    print(f"\nReport: {DOCS_DIR / f'baseline_report{suffix}.md'}")
    print(f"Figures: {', '.join(figures)}")


if __name__ == "__main__":
    main()
