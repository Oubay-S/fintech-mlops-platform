"""Build the primary split + calibration split and fit the shared preprocessor.

Protocols:
- **Primary:** stratified random 80/20 split (stable benchmark / statistics).
- **Robustness:** temporal holdout (later 20% of rows, no hour overlap) —
  used only to quantify drift, never to fit or select models.

Run from the repository root:

    python -m ml.training.scripts.prepare_data            # full data
    python -m ml.training.scripts.prepare_data --sample   # 200k sample
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib

from ml.common.loading import load_paysim
from ml.common.paths import ML_DIR
from ml.common.preprocessing import (
    build_features,
    build_preprocessor,
    stratified_split,
    temporal_split,
    train_calibration_split,
)
from ml.common.schema import TARGET

PROCESSED_DIR = ML_DIR / "data" / "processed"
DOCS_DIR = ML_DIR / "training" / "docs"


def _rate(df) -> float:
    return float(df[TARGET].mean())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", action="store_true", help="use the 200k sample")
    args = parser.parse_args()

    df = load_paysim(sample=args.sample)

    # ---- primary protocol: stratified random split -------------------------
    train_df, test_df = stratified_split(df, test_frac=0.2, random_state=42)
    fit_df, cal_df = train_calibration_split(train_df, cal_frac=0.2, random_state=42)

    features = build_features(fit_df)
    preprocessor = build_preprocessor()
    preprocessor.fit(features)
    feature_names = list(preprocessor.get_feature_names_out())

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(preprocessor, PROCESSED_DIR / "preprocessor.joblib")

    # ---- robustness protocol: temporal holdout -----------------------------
    temporal_train, temporal_test = temporal_split(df, test_frac=0.2)

    metadata = {
        "dataset": "sample" if args.sample else "full",
        "rows": len(df),
        "primary_protocol": {
            "name": "stratified random split",
            "random_state": 42,
            "train_rows": len(train_df),
            "calibration_rows": len(cal_df),
            "fit_rows": len(fit_df),
            "test_rows": len(test_df),
            "fraud_rate": {
                "train": _rate(train_df),
                "fit": _rate(fit_df),
                "calibration": _rate(cal_df),
                "test": _rate(test_df),
            },
        },
        "temporal_robustness": {
            "name": "temporal holdout (later rows, no hour overlap)",
            "train_rows": len(temporal_train),
            "test_rows": len(temporal_test),
            "train_step_range": [
                int(temporal_train["step"].min()),
                int(temporal_train["step"].max()),
            ],
            "test_step_range": [
                int(temporal_test["step"].min()),
                int(temporal_test["step"].max()),
            ],
            "fraud_rate": {
                "train": _rate(temporal_train),
                "test": _rate(temporal_test),
            },
        },
        "feature_names": feature_names,
        "n_features": len(feature_names),
        "preprocessor": "ml/common/preprocessing.py::build_preprocessor",
    }

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    (DOCS_DIR / "preprocessing_metadata.json").write_text(json.dumps(metadata, indent=2))

    print(json.dumps(metadata, indent=2))
    print(f"\nSaved preprocessor: {PROCESSED_DIR / 'preprocessor.joblib'}")
    print(f"Saved metadata: {DOCS_DIR / 'preprocessing_metadata.json'}")


if __name__ == "__main__":
    main()
