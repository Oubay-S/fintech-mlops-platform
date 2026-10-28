"""The benchmark config is part of the Phase 4 contract; keep it loadable."""
from __future__ import annotations

import yaml

from ml.common.paths import ML_DIR
from ml.training.scripts.run_benchmark import PROTOCOLS


def test_benchmark_config_loads() -> None:
    path = ML_DIR / "training" / "configs" / "benchmark.yaml"
    config = yaml.safe_load(path.read_text())
    assert config["populations"]["primary"] == "app_valid"
    assert {"lr", "rf", "xgb", "svm", "mlp"} <= set(config["models"])
    assert config["cv"]["folds"] >= 2
    assert len(config["cv"]["seeds"]) >= 1
    assert config["models"]["svm"]["max_train_rows"] > 0


def test_protocols() -> None:
    assert {"contract", "restricted", "rule_blind"} <= set(PROTOCOLS)
    assert PROTOCOLS["contract"] is None
    assert "sender_old_balance" not in PROTOCOLS["rule_blind"]
    assert "sender_new_balance" not in PROTOCOLS["restricted"]
