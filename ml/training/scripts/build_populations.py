"""Build the cached benchmark populations from PaySim.

Primary population: app-valid, in-scope — TRANSFER/CASH_OUT, amount > 0 and
amount <= sender_old_balance (the app rejects the rest before ML).

Secondary: 1M stratified samples of the in-scope and all-types frames; 100k
app-valid sample for smoke tests/SVM; per-type app-valid frames.

Run from the repository root:

    python -m ml.training.scripts.build_populations
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
from sklearn.model_selection import train_test_split

from ml.common.loading import load_paysim
from ml.common.paths import ML_DIR
from ml.common.schema import TARGET

POP_DIR = ML_DIR / "data" / "processed" / "populations"
TRANSFER_TYPES = ["TRANSFER", "CASH_OUT"]


def _stratified_sample(df: pd.DataFrame, n: int, seed: int) -> pd.DataFrame:
    if len(df) <= n:
        return df.reset_index(drop=True)
    sample, _ = train_test_split(
        df, train_size=n, stratify=df[TARGET], random_state=seed
    )
    return sample.reset_index(drop=True)


def _save(df: pd.DataFrame, name: str) -> dict:
    path = POP_DIR / f"{name}.parquet"
    df.to_parquet(path, index=False)
    return {
        "file": str(path.relative_to(ML_DIR.parent)),
        "rows": int(len(df)),
        "frauds": int(df[TARGET].sum()),
        "fraud_rate": float(df[TARGET].mean()),
        "types": {str(k): int(v) for k, v in df["type"].value_counts().items()},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--sample-size", type=int, default=1_000_000)
    parser.add_argument("--small-size", type=int, default=100_000)
    args = parser.parse_args()

    POP_DIR.mkdir(parents=True, exist_ok=True)
    df = load_paysim()

    in_scope = df[df["type"].isin(TRANSFER_TYPES)].reset_index(drop=True)
    app_valid = in_scope[
        (in_scope["amount"] > 0) & (in_scope["amount"] <= in_scope["oldbalanceOrg"])
    ].reset_index(drop=True)

    populations = {
        "app_valid": app_valid,
        "app_valid_sample_100k": _stratified_sample(app_valid, args.small_size, args.seed),
        "in_scope_sample_1m": _stratified_sample(in_scope, args.sample_size, args.seed),
        "all_types_sample_1m": _stratified_sample(df, args.sample_size, args.seed),
        "transfer_app_valid": app_valid[app_valid["type"] == "TRANSFER"].reset_index(drop=True),
        "cash_out_app_valid": app_valid[app_valid["type"] == "CASH_OUT"].reset_index(drop=True),
    }

    metadata = {
        "source": "ml/data/paysim/paysim.parquet (git-ignored)",
        "seed": args.seed,
        "filters": {
            "in_scope": "type in [TRANSFER, CASH_OUT]",
            "app_valid": "in_scope and amount > 0 and amount <= oldbalanceOrg",
            "samples": f"stratified on {TARGET}; 1M / 100k",
        },
        "populations": {name: _save(frame, name) for name, frame in populations.items()},
    }
    (POP_DIR / "populations_metadata.json").write_text(json.dumps(metadata, indent=2))
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
