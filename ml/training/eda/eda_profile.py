"""First EDA pass on PaySim: quality checks, key statistics, figures and a report.

Run from the repository root:

    python -m ml.training.eda.eda_profile
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from ml.common.loading import load_paysim
from ml.common.paths import FULL_PARQUET

ML_DIR = Path(__file__).resolve().parents[2]
REPORT_DIR = ML_DIR / "training" / "docs"
FIG_DIR = REPORT_DIR / "figures"

TRANSFER_TYPES = ["TRANSFER", "CASH_OUT"]
COLORS = {0: "#4C78A8", 1: "#E45756"}


def _md_table(df: pd.DataFrame) -> str:
    """Render a small DataFrame as a Markdown table (no extra dependency)."""
    columns = [str(c) for c in df.columns]
    lines = ["| " + " | ".join(columns) + " |", "|" + "|".join(["---"] * len(columns)) + "|"]
    for _, row in df.iterrows():
        values = []
        for value in row:
            if isinstance(value, (int, np.integer)):
                values.append(f"{value:,}")
            elif isinstance(value, float):
                values.append(f"{value:,.4f}")
            else:
                values.append(str(value))
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def _save(fig: plt.Figure, name: str) -> None:
    fig.tight_layout()
    fig.savefig(FIG_DIR / name, dpi=150)
    plt.close(fig)


def main() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)

    df = load_paysim()
    n_rows, n_cols = len(df), df.shape[1]
    memory_mb = df.memory_usage(deep=True).sum() / 1e6
    missing_cells = int(df.isna().sum().sum())
    duplicate_rows = int(df.duplicated().sum())

    n_fraud = int(df["isFraud"].sum())
    n_legit = n_rows - n_fraud
    fraud_rate = n_fraud / n_rows * 100

    class_balance = pd.DataFrame(
        {
            "class": ["0 — legitimate", "1 — fraud"],
            "count": [n_legit, n_fraud],
            "share_pct": [n_legit / n_rows * 100, fraud_rate],
        }
    )

    by_type = (
        df.groupby("type", observed=True)["isFraud"]
        .agg(count="size", frauds="sum")
        .assign(rate_pct=lambda d: d["frauds"] / d["count"] * 100)
        .reset_index()
    )

    amount_by_class = df.groupby("isFraud")["amount"].describe().reset_index()

    consistency = ((df["newbalanceOrig"] - (df["oldbalanceOrg"] - df["amount"])).abs() <= 0.01)
    cons_by_type = (
        df.assign(consistent=consistency)
        .groupby("type", observed=True)["consistent"]
        .mean()
        .mul(100)
        .reset_index(name="consistent_pct")
    )
    overall_consistent = float(consistency.mean() * 100)

    rule_mask = (df["amount"] == df["oldbalanceOrg"]) & df["type"].isin(TRANSFER_TYPES)
    rule_rows = int(rule_mask.sum())
    rule_frauds = int(df.loc[rule_mask, "isFraud"].sum())
    rule_rate = rule_frauds / rule_rows * 100 if rule_rows else 0.0
    rule_coverage = rule_frauds / n_fraud * 100 if n_fraud else 0.0

    zero_after = (
        df.assign(zero=df["newbalanceOrig"] == 0)
        .groupby("isFraud")["zero"]
        .mean()
        .mul(100)
        .reset_index(name="zero_balance_pct")
    )

    orig_counts = df["nameOrig"].value_counts()
    orig_unique = int(orig_counts.size)
    orig_once_pct = float((orig_counts == 1).mean() * 100)
    orig_top_freq = int(orig_counts.iloc[0])
    dest_unique = int(df["nameDest"].nunique())

    flagged_rows = int(df["isFlaggedFraud"].sum())
    flagged_frauds = int(df.loc[df["isFlaggedFraud"] == 1, "isFraud"].sum())

    # ---- figures -------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.bar(["legitimate", "fraud"], [n_legit, n_fraud], color=[COLORS[0], COLORS[1]])
    ax.set_yscale("log")
    ax.set_ylabel("transactions (log scale)")
    ax.set_title("PaySim — class balance")
    for i, value in enumerate([n_legit, n_fraud]):
        ax.text(i, value, f"{value:,}", ha="center", va="bottom", fontsize=9)
    _save(fig, "01_class_balance.png")

    fig, ax = plt.subplots(figsize=(7, 4))
    ax.bar(by_type["type"].astype(str), by_type["rate_pct"], color=COLORS[1])
    ax.set_ylabel("fraud rate (%)")
    ax.set_title("PaySim — fraud rate by transaction type")
    for i, value in enumerate(by_type["rate_pct"]):
        ax.text(i, value, f"{value:.3f}%", ha="center", va="bottom", fontsize=8)
    _save(fig, "02_fraud_rate_by_type.png")

    fig, ax = plt.subplots(figsize=(8, 4))
    bins = np.logspace(np.log10(0.01), np.log10(df["amount"].max()), 60)
    for label, name in [(0, "legitimate"), (1, "fraud")]:
        values = df.loc[df["isFraud"] == label, "amount"].clip(lower=0.01)
        ax.hist(values, bins=bins, alpha=0.55, label=name, color=COLORS[label], density=True)
    ax.set_xscale("log")
    ax.set_xlabel("amount (log scale)")
    ax.set_ylabel("density")
    ax.set_title("PaySim — amount distribution by class")
    ax.legend()
    _save(fig, "03_amount_by_class.png")

    fig, ax = plt.subplots(figsize=(7, 4))
    ax.bar(cons_by_type["type"].astype(str), cons_by_type["consistent_pct"], color="#54A24B")
    ax.set_ylabel("% rows where new = old − amount")
    ax.set_title("PaySim — balance arithmetic consistency")
    ax.set_ylim(0, 105)
    for i, value in enumerate(cons_by_type["consistent_pct"]):
        ax.text(i, value, f"{value:.1f}%", ha="center", va="bottom", fontsize=8)
    _save(fig, "04_balance_consistency.png")

    fig, ax = plt.subplots(figsize=(6, 4))
    ax.bar(["legitimate", "fraud"], zero_after["zero_balance_pct"], color=[COLORS[0], COLORS[1]])
    ax.set_ylabel("% with newbalanceOrig == 0")
    ax.set_title("PaySim — zero balance after the transaction")
    ax.set_ylim(0, 105)
    for i, value in enumerate(zero_after["zero_balance_pct"]):
        ax.text(i, value, f"{value:.1f}%", ha="center", va="bottom", fontsize=9)
    _save(fig, "05_zero_balance_after.png")

    # ---- report --------------------------------------------------------------
    report = f"""# PaySim — EDA Report (first pass)

**Generated:** 2026-10-21 · **Script:** `ml/training/eda/eda_profile.py`
**Dataset:** `{FULL_PARQUET}`

## 1. Shape and quality

| Metric | Value |
|---|---|
| Rows | {n_rows:,} |
| Columns | {n_cols} |
| Missing cells | {missing_cells:,} |
| Duplicate rows | {duplicate_rows:,} |
| In-memory size | {memory_mb:,.0f} MB |

## 2. Target distribution

{_md_table(class_balance)}

## 3. Fraud by transaction type

{_md_table(by_type)}

## 4. Amount by class

{_md_table(amount_by_class)}

## 5. Balance arithmetic consistency

Rows satisfying `newbalanceOrig = oldbalanceOrg − amount` (tolerance 0.01): **{overall_consistent:.2f}%**.

{_md_table(cons_by_type)}

## 6. The trivial rule

Rows with `amount == oldbalanceOrg` on TRANSFER/CASH_OUT:

- Rows selected: **{rule_rows:,}**
- Fraud among them: **{rule_frauds:,}** ({rule_rate:.2f}%)
- Share of all frauds covered: **{rule_coverage:.2f}%**

This is a property of the simulator. It is why the contract model is expected to score near-perfectly; the restricted ablation (without the new-balance fields) will quantify it.

## 7. `newbalanceOrig == 0`

{_md_table(zero_after)}

## 8. Account identity

| Metric | Value |
|---|---|
| Unique `nameOrig` | {orig_unique:,} |
| Share appearing exactly once | {orig_once_pct:.2f}% |
| Max occurrences of one `nameOrig` | {orig_top_freq} |
| Unique `nameDest` | {dest_unique:,} |

## 9. `isFlaggedFraud`

- Flagged rows: **{flagged_rows}**
- Of those, actual frauds: **{flagged_frauds}**
- This column is a rule output and is **never** used as a feature.

## 10. Figures

![Class balance](figures/01_class_balance.png)
![Fraud rate by type](figures/02_fraud_rate_by_type.png)
![Amount distribution](figures/03_amount_by_class.png)
![Balance consistency](figures/04_balance_consistency.png)
![Zero balance after](figures/05_zero_balance_after.png)

## 11. Findings

1. Fraud is rare ({fraud_rate:.3f}%) and exists only in TRANSFER and CASH_OUT.
2. The label is near-deterministic: `amount == oldbalanceOrg` covers {rule_coverage:.2f}% of frauds with {rule_rate:.2f}% precision.
3. Balance arithmetic is inconsistent on most rows, so balance-based reasoning is artificial.
4. {orig_once_pct:.2f}% of sender accounts appear once — no sender-history features.
5. The contract model will be near-perfect; the restricted ablation and decision-level evaluation are mandatory for a credible report.

## 12. Next steps

- Phase 2: shared preprocessing module, temporal split + calibration split, leakage guards.
- Baseline (Logistic Regression) with the full metric suite.
"""
    report_path = REPORT_DIR / "eda_report.md"
    report_path.write_text(report)

    summary = {
        "rows": n_rows,
        "columns": n_cols,
        "missing_cells": missing_cells,
        "duplicate_rows": duplicate_rows,
        "fraud": n_fraud,
        "fraud_rate_pct": round(fraud_rate, 4),
        "rule_rows": rule_rows,
        "rule_frauds": rule_frauds,
        "rule_precision_pct": round(rule_rate, 2),
        "rule_coverage_pct": round(rule_coverage, 2),
        "balance_consistent_pct": round(overall_consistent, 2),
        "unique_name_orig": orig_unique,
        "name_orig_once_pct": round(orig_once_pct, 2),
        "unique_name_dest": dest_unique,
        "flagged_rows": flagged_rows,
        "flagged_actual_frauds": flagged_frauds,
    }
    (REPORT_DIR / "eda_summary.json").write_text(json.dumps(summary, indent=2))

    print("EDA report:", report_path)
    print("Figures:", FIG_DIR)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
