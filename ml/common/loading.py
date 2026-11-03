"""Load PaySim from the local Parquet cache."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .paths import dataset_path
from .schema import assert_paysim_schema


def load_paysim(
    *,
    sample: bool = False,
    path: str | Path | None = None,
    columns: list[str] | None = None,
) -> pd.DataFrame:
    """Load the full dataset (default) or the 200k stratified sample.

    Set ``PAYSIM_PATH`` (full file) or ``PAYSIM_DATA_DIR`` (folder) to override
    the default ``ml/data/paysim/`` location.
    """
    parquet_path = Path(path) if path is not None else dataset_path(sample=sample)
    if not parquet_path.exists():
        raise FileNotFoundError(
            f"{parquet_path} not found. Place the Parquet cache under ml/data/paysim/ "
            "or set PAYSIM_PATH / PAYSIM_DATA_DIR."
        )

    df = pd.read_parquet(parquet_path, columns=columns)
    if columns is None:
        assert_paysim_schema(df)
    if "type" in df.columns:
        df["type"] = df["type"].astype("category")
    return df


def load_sample() -> pd.DataFrame:
    """Convenience loader for the 200k development sample."""
    return load_paysim(sample=True)
