"""Tests for the preprocessing pipeline and the split logic."""
from __future__ import annotations

import numpy as np

from ml.common.loading import load_sample
from ml.common.preprocessing import (
    build_features,
    build_preprocessor,
    build_target,
    stratified_split,
    temporal_split,
    train_calibration_split,
)
from ml.common.schema import TARGET


def _rate(df) -> float:
    return float(df[TARGET].mean())


def _primary_splits():
    df = load_sample()
    train_df, test_df = stratified_split(df, test_frac=0.2, random_state=42)
    fit_df, cal_df = train_calibration_split(train_df, cal_frac=0.2, random_state=42)
    return df, train_df, test_df, fit_df, cal_df


def test_stratified_split() -> None:
    df, train_df, test_df, _, _ = _primary_splits()
    assert len(train_df) + len(test_df) == len(df)
    assert abs(_rate(train_df) - _rate(test_df)) < 0.0005


def test_temporal_split_boundary() -> None:
    df = load_sample()
    train_df, test_df = temporal_split(df, test_frac=0.2)
    assert len(train_df) + len(test_df) == len(df)
    assert train_df["step"].max() < test_df["step"].min()
    assert 0.15 <= len(test_df) / len(df) <= 0.25


def test_calibration_split_is_inside_train() -> None:
    _, train_df, _, fit_df, cal_df = _primary_splits()
    assert len(fit_df) + len(cal_df) == len(train_df)
    assert abs(_rate(fit_df) - _rate(cal_df)) < 0.0005


def test_target_alignment() -> None:
    _, _, _, fit_df, _ = _primary_splits()
    target = build_target(fit_df)
    assert len(target) == len(fit_df)
    assert target.equals(fit_df[TARGET].reset_index(drop=True))


def test_preprocessor_shape_and_names() -> None:
    _, _, _, fit_df, _ = _primary_splits()
    features = build_features(fit_df)
    preprocessor = build_preprocessor()
    transformed = preprocessor.fit_transform(features)
    names = list(preprocessor.get_feature_names_out())

    assert transformed.shape[0] == len(fit_df)
    assert transformed.shape[1] == 14  # 9 numeric + 5 type categories
    assert "amount" in names
    assert "balance_drain_ratio" in names
    assert "type_TRANSFER" in names


def test_preprocessor_is_deterministic() -> None:
    _, _, _, fit_df, _ = _primary_splits()
    features = build_features(fit_df)
    preprocessor = build_preprocessor().fit(features)

    first = preprocessor.transform(features.head(100))
    second = preprocessor.transform(features.head(100))
    np.testing.assert_allclose(first, second)


def test_serving_parity_single_row() -> None:
    df, _, _, fit_df, _ = _primary_splits()
    preprocessor = build_preprocessor().fit(build_features(fit_df))

    raw_row = df.iloc[[0]]
    batch = build_features(df.iloc[[0, 1]]).reset_index(drop=True)
    batch_transformed = preprocessor.transform(batch)
    single_transformed = preprocessor.transform(build_features(raw_row).reset_index(drop=True))

    np.testing.assert_allclose(
        single_transformed[0], batch_transformed[0], rtol=1e-10, atol=1e-12
    )
