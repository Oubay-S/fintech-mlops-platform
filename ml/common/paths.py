"""Path resolution for the local PaySim dataset (git-ignored)."""
from __future__ import annotations

import os
from pathlib import Path

ML_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = ML_DIR.parent

DATA_DIR = Path(os.environ.get("PAYSIM_DATA_DIR", ML_DIR / "data" / "paysim"))
FULL_PARQUET = Path(os.environ.get("PAYSIM_PATH", DATA_DIR / "paysim.parquet"))
SAMPLE_PARQUET = DATA_DIR / "paysim_sample_200k.parquet"
RAW_CSV = DATA_DIR / "raw" / "PS_20174392719_1491204439457_log.csv"


def dataset_path(sample: bool = False) -> Path:
    """Return the Parquet path for the sample or the full dataset."""
    return SAMPLE_PARQUET if sample else FULL_PARQUET
