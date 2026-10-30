"""Schema and feature-contract definitions for PaySim."""
from __future__ import annotations

import pandas as pd

PAYSIM_COLUMNS = [
    "step",
    "type",
    "amount",
    "nameOrig",
    "oldbalanceOrg",
    "newbalanceOrig",
    "nameDest",
    "oldbalanceDest",
    "newbalanceDest",
    "isFraud",
    "isFlaggedFraud",
]

# The six fields the application sends to /predict (see FEATURE_LIST_V1.md).
CONTRACT_FEATURES = [
    "type",
    "amount",
    "sender_old_balance",
    "sender_new_balance",
    "receiver_old_balance",
    "receiver_new_balance",
]

# PaySim column -> contract field.
PAYSIM_TO_CONTRACT = {
    "type": "type",
    "amount": "amount",
    "oldbalanceOrg": "sender_old_balance",
    "newbalanceOrig": "sender_new_balance",
    "oldbalanceDest": "receiver_old_balance",
    "newbalanceDest": "receiver_new_balance",
}

# Features derived inside the ML service from the six contract fields.
DERIVED_FEATURES = [
    "balance_drain_ratio",
    "receiver_gain_ratio",
    "sender_zero_after",
    "amount_equals_old_balance",
]

FEATURE_COLUMNS = CONTRACT_FEATURES + DERIVED_FEATURES
TARGET = "isFraud"

# Model-input groups (after contract mapping + derived features).
NUMERIC_FEATURES = [
    "amount",
    "sender_old_balance",
    "sender_new_balance",
    "receiver_old_balance",
    "receiver_new_balance",
] + DERIVED_FEATURES
CATEGORICAL_FEATURES = ["type"]

# Canonical order of in-scope PaySim categories for OneHotEncoder (`CASH_OUT`, `TRANSFER`)
# matching the application scope (Rule R1b) and the trained model's 11-column signature.
TRANSACTION_TYPES = ["CASH_OUT", "TRANSFER"]

# Columns that must never enter the feature matrix (leakage / identifiers / non-contract).
FORBIDDEN_FEATURES = ["isFlaggedFraud", "step", "nameOrig", "nameDest"]


def assert_paysim_schema(df: pd.DataFrame) -> None:
    """Raise if any expected PaySim column is missing."""
    missing = [c for c in PAYSIM_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing PaySim columns: {missing}")


def assert_no_forbidden_columns(df: pd.DataFrame) -> None:
    """Raise if a forbidden column (leakage / identifier) is present."""
    leaked = [c for c in FORBIDDEN_FEATURES if c in df.columns]
    if leaked:
        raise ValueError(f"Forbidden columns in feature matrix: {leaked}")
