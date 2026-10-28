"""Shared metric helpers for the baseline and benchmark runners."""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    matthews_corrcoef,
    precision_score,
    recall_score,
    roc_auc_score,
)

from ml.common.schema import TARGET

TRANSFER_TYPES = ["TRANSFER", "CASH_OUT"]


def metrics_at(y_true: np.ndarray, probs: np.ndarray, threshold: float = 0.5) -> dict:
    """Full metric suite for one slice; AUCs are None for single-class slices."""
    y_true = np.asarray(y_true)
    probs = np.asarray(probs)
    predicted = (probs >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_true, predicted, labels=[0, 1]).ravel()
    has_both_classes = len(np.unique(y_true)) == 2
    return {
        "threshold": float(threshold),
        "accuracy": float(accuracy_score(y_true, predicted)),
        "precision": float(precision_score(y_true, predicted, zero_division=0)),
        "recall": float(recall_score(y_true, predicted, zero_division=0)),
        "f1": float(f1_score(y_true, predicted, zero_division=0)),
        "roc_auc": float(roc_auc_score(y_true, probs)) if has_both_classes else None,
        "pr_auc": float(average_precision_score(y_true, probs)) if has_both_classes else None,
        "mcc": float(matthews_corrcoef(y_true, predicted)),
        "brier": float(brier_score_loss(y_true, probs)),
        "predicted_positive_rate": float(predicted.mean()),
        "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
    }


def subset_metrics(
    df: pd.DataFrame,
    probs: np.ndarray,
    mask: np.ndarray,
    name: str,
    threshold: float = 0.5,
) -> dict:
    """Metrics on a boolean slice of a frame."""
    y = df.loc[mask, TARGET].to_numpy()
    result = metrics_at(y, np.asarray(probs)[mask], threshold=threshold)
    result.update(
        {
            "name": name,
            "rows": int(len(y)),
            "frauds": int(y.sum()),
            "fraud_rate": float(y.mean()) if len(y) else 0.0,
        }
    )
    return result


def rule_baseline(df: pd.DataFrame, mask: np.ndarray | None = None) -> dict:
    """The deterministic PaySim rule as a model: amount == oldbalanceOrg."""
    subset = df if mask is None else df.loc[mask]
    y = subset[TARGET].to_numpy()
    selected = (
        (subset["amount"] == subset["oldbalanceOrg"])
        & subset["type"].isin(TRANSFER_TYPES)
    ).to_numpy()
    tp = int((selected & (y == 1)).sum())
    fp = int((selected & (y == 0)).sum())
    fn = int((~selected & (y == 1)).sum())
    tn = int((~selected & (y == 0)).sum())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "rows": int(len(y)),
        "frauds": int(y.sum()),
        "selected": int(selected.sum()),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": float(precision),
        "recall": float(recall),
        "f1": float(f1),
    }


def fmt_metric(value, digits: int = 4) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"
