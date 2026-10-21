"""Tests for the shared loading/preprocessing module (drift guard)."""
from __future__ import annotations

from ml.common.loading import load_sample
from ml.common.preprocessing import build_features, temporal_split, to_contract_frame
from ml.common.schema import CONTRACT_FEATURES, DERIVED_FEATURES, FORBIDDEN_FEATURES


def test_sample_shape() -> None:
    df = load_sample()
    assert len(df) == 200_000
    assert "isFraud" in df.columns


def test_contract_mapping() -> None:
    df = load_sample()
    contract = to_contract_frame(df)
    assert list(contract.columns) == CONTRACT_FEATURES


def test_build_features() -> None:
    df = load_sample()
    features = build_features(df)
    assert len(features) == len(df)
    for column in CONTRACT_FEATURES + DERIVED_FEATURES:
        assert column in features.columns
    for column in FORBIDDEN_FEATURES:
        assert column not in features.columns


def test_derived_flags_are_binary() -> None:
    features = build_features(load_sample())
    assert set(features["sender_zero_after"].unique()) <= {0, 1}
    assert set(features["amount_equals_old_balance"].unique()) <= {0, 1}


def test_temporal_split() -> None:
    df = load_sample()
    train, test = temporal_split(df, test_frac=0.2)
    assert len(train) + len(test) == len(df)
    assert len(test) == 40_000
    assert train["step"].max() <= test["step"].min()
