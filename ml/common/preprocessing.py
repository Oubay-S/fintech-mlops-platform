"""Shared preprocessing for training and serving.

Every derived feature is computable at decision time from the six contract
fields. The same module is imported by the training pipeline and by the
serving code (parity is enforced by tests).
"""
from __future__ import annotations

import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from .schema import (
    CATEGORICAL_FEATURES,
    CONTRACT_FEATURES,
    NUMERIC_FEATURES,
    PAYSIM_TO_CONTRACT,
    TARGET,
    TRANSACTION_TYPES,
)


def to_contract_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Map PaySim columns (or already-mapped contract columns) to the six production contract names."""
    if all(c in df.columns for c in CONTRACT_FEATURES):
        return df[list(CONTRACT_FEATURES)].copy()
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


def build_target(df: pd.DataFrame) -> pd.Series:
    """Return the target aligned with ``build_features`` output."""
    if TARGET not in df.columns:
        raise ValueError(f"Missing target column: {TARGET}")
    return df[TARGET].reset_index(drop=True)


def build_preprocessor() -> ColumnTransformer:
    """The single preprocessing object used by training and serving.

    - numeric contract fields + derived features: StandardScaler
    - ``type``: one-hot encoding with explicit 5 PaySim categories

    Scaling is harmless for tree models and required for LR/SVM/MLP, so one
    transformation keeps the benchmark fair and the serving path identical.
    """
    return ColumnTransformer(
        transformers=[
            ("num", StandardScaler(), NUMERIC_FEATURES),
            (
                "cat",
                OneHotEncoder(
                    categories=[TRANSACTION_TYPES],
                    handle_unknown="ignore",
                    sparse_output=False,
                ),
                CATEGORICAL_FEATURES,
            ),
        ],
        remainder="drop",
        verbose_feature_names_out=False,
    )


def temporal_split(
    df: pd.DataFrame,
    *,
    test_frac: float = 0.2,
    time_col: str = "step",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Temporal holdout (robustness): train = earlier rows, test = later rows."""
    if not 0 < test_frac < 1:
        raise ValueError("test_frac must be in (0, 1)")
    if time_col not in df.columns:
        raise ValueError(f"Missing time column: {time_col}")

    ordered = df.sort_values(time_col, kind="mergesort").reset_index(drop=True)
    cut_idx = int(len(ordered) * (1 - test_frac))
    cut_idx = max(1, min(len(ordered) - 1, cut_idx))
    cut_step = ordered.iloc[cut_idx][time_col]

    train = ordered[ordered[time_col] < cut_step].reset_index(drop=True)
    test = ordered[ordered[time_col] >= cut_step].reset_index(drop=True)
    if train.empty or test.empty:
        raise ValueError("Temporal split produced an empty train or test set")
    return train, test


def stratified_split(
    df: pd.DataFrame,
    *,
    test_frac: float = 0.2,
    random_state: int = 42,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Primary split: stratified random train/test split."""
    if not 0 < test_frac < 1:
        raise ValueError("test_frac must be in (0, 1)")
    if TARGET not in df.columns:
        raise ValueError(f"Missing target column: {TARGET}")

    train_df, test_df = train_test_split(
        df,
        test_size=test_frac,
        random_state=random_state,
        stratify=df[TARGET],
    )
    return train_df.reset_index(drop=True), test_df.reset_index(drop=True)


def train_calibration_split(
    train_df: pd.DataFrame,
    *,
    cal_frac: float = 0.2,
    random_state: int = 42,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Carve a calibration set out of the training period (stratified)."""
    if not 0 < cal_frac < 1:
        raise ValueError("cal_frac must be in (0, 1)")
    if TARGET not in train_df.columns:
        raise ValueError(f"Missing target column: {TARGET}")

    fit_df, cal_df = train_test_split(
        train_df,
        test_size=cal_frac,
        random_state=random_state,
        stratify=train_df[TARGET],
    )
    return fit_df.reset_index(drop=True), cal_df.reset_index(drop=True)
