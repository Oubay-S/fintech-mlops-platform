"""Test bootstrap for the ML tests.

The real 200k PaySim sample is git-ignored, so CI has no data. When the sample
is absent, generate a synthetic 200k-row PaySim-format frame in a temporary
directory and point ``PAYSIM_DATA_DIR`` at it *before* ``ml.common.paths`` is
imported. The tests then exercise the code paths (splits, derived features,
preprocessor shape, determinism, train/serve parity) without shipping data.

Local runs with the real sample are unchanged: the real file wins.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

_ML_DIR = Path(__file__).resolve().parents[2]
_REAL_SAMPLE = _ML_DIR / "data" / "paysim" / "paysim_sample_200k.parquet"

_force_synthetic = os.environ.get("PAYSIM_TEST_FORCE_SYNTHETIC") == "1"
_custom_dir = os.environ.get("PAYSIM_DATA_DIR")

if (_force_synthetic or not _REAL_SAMPLE.exists()) and not _custom_dir:
    _tmp_dir = Path(tempfile.mkdtemp(prefix="paysim-test-"))
    _rng = np.random.default_rng(42)
    _n = 200_000

    _types = np.array(["TRANSFER", "CASH_OUT", "CASH_IN", "PAYMENT", "DEBIT"])
    _type = _rng.choice(_types, size=_n, p=[0.084, 0.352, 0.220, 0.338, 0.006])

    _amount = _rng.lognormal(mean=10.8, sigma=1.1, size=_n).round(2)
    _old_org = _rng.lognormal(mean=10.9, sigma=1.2, size=_n).round(2)

    # A slice of rule-positive rows (amount == old balance) so the derived
    # equality/zero flags are exercised, not all-zero.
    _rule_idx = _rng.choice(_n, size=_n // 100, replace=False)
    _amount[_rule_idx] = _old_org[_rule_idx]

    _new_org = np.maximum(_old_org - _amount, 0).round(2)
    _old_dest = _rng.lognormal(mean=9.5, sigma=1.5, size=_n).round(2)
    _new_dest = (_old_dest + _amount).round(2)

    _fraud = np.zeros(_n, dtype=int)
    _fraud_idx = _rng.choice(_n, size=258, replace=False)
    _fraud[_fraud_idx] = 1
    # Mirror PaySim: fraud only in TRANSFER/CASH_OUT.
    _type[_fraud_idx] = _rng.choice(["TRANSFER", "CASH_OUT"], size=len(_fraud_idx))

    _df = pd.DataFrame(
        {
            "step": _rng.integers(1, 744, size=_n),
            "type": _type,
            "amount": _amount,
            "nameOrig": [f"C{i}" for i in range(_n)],
            "oldbalanceOrg": _old_org,
            "newbalanceOrig": _new_org,
            "nameDest": [f"D{i % 50_000}" for i in range(_n)],
            "oldbalanceDest": _old_dest,
            "newbalanceDest": _new_dest,
            "isFraud": _fraud,
            "isFlaggedFraud": 0,
        }
    )
    _df.to_parquet(_tmp_dir / "paysim_sample_200k.parquet", index=False)
    os.environ["PAYSIM_DATA_DIR"] = str(_tmp_dir)
