"""Shared preprocessing for training and serving.

Every derived feature is computable at decision time from the six contract
fields. The same module is imported by the training pipeline and by the
serving code (parity is enforced by tests).
"""
from __future__ import annotations

import pandas as pd

from .schema import CONTRACT_FEATURES, PAYSIM_TO_CONTRACT


def to_contract_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Map PaySim columns to the six production contract names."""
    missing = [c for c in PAYSIM_TO_CONTRACT if c not in df.columns]
    if missing:
        raise ValueError(f"Missing PaySim columns for contract mapping: {missing}")
    return df[list(PAYSIM_TO_CONTRACT)].rename(columns=PAYSIM_TO_CONTRACT)


def add_derived_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add the derived ratios/flags used by the model.

    The dataframe must already use the contract names (see ``to_contract_frame``).
    """
    missing = [c for c in CONTRACT_FEATURES if c not in df.columns]
    if missing:
        raise ValueError(f"Missing contract columns: {missing}")

    out = df.copy()
    out["balance_drain_ratio"] = out["amount"] / (out["sender_old_balance"] + 1.0)
    out["receiver_gain_ratio"] = out["amount"] / (out["receiver_old_balance"] + 1.0)
    out["sender_zero_after"] = (out["sender_new_balance"] == 0).astype("int8")
    out["amount_equals_old_balance"] = (
        out["amount"] == out["sender_old_balance"]
    ).astype("int8")
    return out


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """Contract mapping + derived features (model input frame)."""
    return add_derived_features(to_contract_frame(df))


def temporal_split(
    df: pd.DataFrame,
    *,
    test_frac: float = 0.2,
    time_col: str = "step",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split by simulation time: earliest part for training, latest for testing."""
    if not 0 < test_frac < 1:
        raise ValueError("test_frac must be in (0, 1)")
    if time_col not in df.columns:
        raise ValueError(f"Missing time column: {time_col}")

    ordered = df.sort_values(time_col, kind="mergesort").reset_index(drop=True)
    cut = int(len(ordered) * (1 - test_frac))
    return ordered.iloc[:cut].copy(), ordered.iloc[cut:].copy()
