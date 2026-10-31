"""Assemble the Role 4 handoff package for ML Serving (no FastAPI here).

Outputs under ``ml/training/package/``:

- ``model_card.md`` — intended use, features, metrics, limitations.
- ``metrics_summary.json`` — the conformal config + validation metrics.
- ``parity_cases.json`` — six-field payloads + expected ML Serving outputs.
- ``uncertainty_config.json`` — copy of the conformal artifact.
- ``feature_list_v1.md`` — copy of the frozen contract.
- ``MANIFEST.json`` — files, model path, versions.

The trained pipeline itself is delivered through MLflow (see
``run_conformal.py --log-mlflow``); the local joblib is only a fallback.

Run from the repository root:

    python -m ml.training.scripts.package_model
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from ml.common.artifact_contract import (
    UncertaintyConfig,
    prediction_set,
    suggested_action,
)
from ml.common.paths import ML_DIR, REPO_ROOT
from ml.common.preprocessing import build_features

DEFAULT_MODEL = ML_DIR / "data" / "processed" / "final_contract_model.joblib"
DEFAULT_CONFIG = ML_DIR / "training" / "docs" / "uncertainty_config.json"
DEFAULT_OUTPUT = ML_DIR / "training" / "package"
FEATURE_LIST = ML_DIR / "training" / "docs" / "feature_list_v1.md"

CASES = [
    {
        "name": "legit_partial_transfer",
        "request_id": "550e8400-e29b-41d4-a716-446655440001",
        "features": {
            "type": "TRANSFER",
            "amount": 1250.50,
            "sender_old_balance": 5000.00,
            "sender_new_balance": 3749.50,
            "receiver_old_balance": 100.00,
            "receiver_new_balance": 1350.50,
        },
    },
    {
        "name": "fraud_full_drain",
        "request_id": "550e8400-e29b-41d4-a716-446655440002",
        "features": {
            "type": "TRANSFER",
            "amount": 250000.00,
            "sender_old_balance": 250000.00,
            "sender_new_balance": 0.00,
            "receiver_old_balance": 0.00,
            "receiver_new_balance": 250000.00,
        },
    },
    {
        "name": "high_amount_legit",
        "request_id": "550e8400-e29b-41d4-a716-446655440003",
        "features": {
            "type": "TRANSFER",
            "amount": 600000.00,
            "sender_old_balance": 1000000.00,
            "sender_new_balance": 400000.00,
            "receiver_old_balance": 0.00,
            "receiver_new_balance": 600000.00,
        },
    },
    {
        "name": "cash_out_withdrawal",
        "request_id": "550e8400-e29b-41d4-a716-446655440004",
        "features": {
            "type": "CASH_OUT",
            "amount": 45000.00,
            "sender_old_balance": 52000.00,
            "sender_new_balance": 7000.00,
            "receiver_old_balance": 120000.00,
            "receiver_new_balance": 165000.00,
        },
    },
    {
        "name": "fraud_full_drain_1m",
        "request_id": "550e8400-e29b-41d4-a716-446655440005",
        "features": {
            "type": "TRANSFER",
            "amount": 1000000.00,
            "sender_old_balance": 1000000.00,
            "sender_new_balance": 0.00,
            "receiver_old_balance": 0.00,
            "receiver_new_balance": 1000000.00,
        },
    },
    {
        "name": "small_partial_transfer",
        "request_id": "550e8400-e29b-41d4-a716-446655440006",
        "features": {
            "type": "TRANSFER",
            "amount": 100.00,
            "sender_old_balance": 1000.00,
            "sender_new_balance": 900.00,
            "receiver_old_balance": 0.00,
            "receiver_new_balance": 100.00,
        },
    },
]


def resolve(path: str | Path) -> Path:
    path = Path(path)
    return path if path.is_absolute() else REPO_ROOT / path


def entropy_score(p_fraud: float) -> float:
    eps = 1e-12
    p = min(max(float(p_fraud), eps), 1.0 - eps)
    entropy = -(p * math.log2(p) + (1 - p) * math.log2(1 - p))
    return float(np.clip(entropy, 0.0, 1.0))


def expected_response(features: dict, pipeline, config: UncertaintyConfig) -> dict:
    frame = pd.DataFrame([features])
    engineered = build_features(frame)
    p = float(pipeline.predict_proba(engineered)[:, 1][0])
    labels = prediction_set(p, config)
    score = entropy_score(p)
    action = suggested_action(labels)
    if action == "ALLOW" and score >= config.high_uncertainty_score_threshold:
        action = "HUMAN_REVIEW"
    return {
        "fraud_probability": round(p, 6),
        "prediction_set": labels,
        "action": action,
        "uncertainty_score": round(score, 6),
    }


def model_card(config: UncertaintyConfig, generated_at: str) -> str:
    m = config.metrics_summary
    return f"""# Model Card — `fraud-detector`

**Generated:** {generated_at} · **Owner:** ML Training (Role 4)
**Algorithm:** {config.algorithm} · **Contract:** feature list v{config.feature_list_version}
**Conformal:** {config.method}, {config.confidence_level:.0%} confidence
**R5 threshold:** {config.metrics_summary.get("r5_threshold_validated", "500000")}

## Intended use

Transaction risk scoring for the wallet's `TRANSFER` and `CASH_OUT` flows,
plus human review under the Risk R1–R6 policy. **Synthetic PaySim data only;
not validated for real money or real-world fraud.**

## Data and features

- App-valid, in-scope population: TRANSFER + CASH_OUT, `amount > 0`,
  `amount <= sender_old_balance`; the app computes both new balances.
- Six contract fields + four derived features; ML Serving accepts all five
  type values; the app sends TRANSFER/CASH_OUT.
- Feature list v{config.feature_list_version}; {len(config.feature_names)} input
  columns; {len(config.transformed_feature_names)} transformed columns.

## Validation metrics (app-valid test)

| Metric | Value |
|---|---:|
| ROC-AUC | {m.get("roc_auc", "n/a")} |
| PR-AUC | {m.get("pr_auc", "n/a")} |
| F1 | {m.get("f1", "n/a")} |
| Precision | {m.get("precision", "n/a")} |
| Recall | {m.get("recall", "n/a")} |
| MCC | {m.get("mcc", "n/a")} |
| Brier | {m.get("brier_score", "n/a")} |
| Hard-subset recall | {m.get("hard_subset_recall", "n/a")} |
| Expected review rate | {m.get("expected_review_rate", "n/a")} |
| Model-uncertain rate | {m.get("model_uncertain_rate", "n/a")} |
| Amount-high rate | {m.get("amount_high_rate", "n/a")} |
| Inference p95 (ms) | {m.get("inference_p95_ms", "n/a")} |

## Decision policy

R3 `{{fraud}}` → reject; R4 `{{legit,fraud}}`/`[]` → review; R5 `{{legit}}` +
amount ≥ threshold → review; R6 `{{legit}}` → approve. The R5 share is
rule-driven; the R4 share is model-driven. No legitimate test transaction was
rejected in R3; all app-valid test frauds were caught.

## Limitations

1. **PaySim trivial rule:** `amount == sender_old_balance` is 100% fraud and
   covers ~98% of frauds. The headline is the simulator, not model capability.
2. **Legitimate full drain:** a whole-balance transfer is rejected by R3; V2.2
   uses it as the demo fraud case. The legitimate-user UX is open.
3. **App-valid selection bias:** `available >= amount` removes ~90% of PaySim
   rows; the app-valid fraud rate is ~2.9%, not the full-serving 0.297%.
4. **Temporal drift:** the late-period fraud rate is ~7.36%; conformal fraud
   coverage is 97.92%, but all uncovered frauds are R4 review.
5. **No sender history** (99.85% unique senders) and a single fraud pattern.
6. **Receivers:** destination-disjoint evaluation is clean; the model is not
   validated on unseen real-world mule behaviour.

## Handoff

- MLflow: `models:/fraud-detector@production`, companion `uncertainty_config.json`.
- Serving path: `build_features` (contract-named) → `pipeline.predict_proba` →
  `prediction_set` from the config.
- Parity fixture: `parity_cases.json`.
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=str(DEFAULT_MODEL))
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--feature-list", default=str(FEATURE_LIST))
    args = parser.parse_args()

    artifact = joblib.load(resolve(args.model))
    pipeline = artifact["pipeline"]
    config = UncertaintyConfig.from_dict(artifact["config"])
    if resolve(args.config).exists():
        config = UncertaintyConfig.load(resolve(args.config))
    config.validate()

    output = resolve(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc).isoformat()

    config.save(output / "uncertainty_config.json")
    shutil.copy2(resolve(args.feature_list), output / "feature_list_v1.md")
    (output / "model_card.md").write_text(model_card(config, generated_at))

    metrics = {
        "model": "fraud-detector",
        "algorithm": config.algorithm,
        "generated_at": generated_at,
        "conformal": {
            "method": config.method,
            "confidence_level": config.confidence_level,
            "target_review_rate": config.target_review_rate,
            "q_hat_fraud": config.q_hat_fraud,
            "q_hat_legit": config.q_hat_legit,
            "high_uncertainty_score_threshold": config.high_uncertainty_score_threshold,
        },
        "metrics_summary": config.metrics_summary,
        "feature_names": config.feature_names,
        "transformed_feature_names": config.transformed_feature_names,
        "dataset_version": config.dataset_version,
        "feature_list_version": config.feature_list_version,
        "eval_population": config.eval_population,
        "calibration_rows": config.calibration_rows,
        "calibration_frauds": config.calibration_frauds,
    }
    (output / "metrics_summary.json").write_text(json.dumps(metrics, indent=2))

    parity = {
        "schema_version": "1.0",
        "model": "fraud-detector",
        "generated_at": generated_at,
        "cases": [
            {
                "name": case["name"],
                "request": {
                    "schema_version": "1.0",
                    "request_id": case["request_id"],
                    "features": case["features"],
                },
                "expected": expected_response(case["features"], pipeline, config),
            }
            for case in CASES
        ],
    }
    (output / "parity_cases.json").write_text(json.dumps(parity, indent=2))

    manifest = {
        "generated_at": generated_at,
        "model_path": str(resolve(args.model)),
        "files": [
            "uncertainty_config.json",
            "metrics_summary.json",
            "model_card.md",
            "parity_cases.json",
            "feature_list_v1.md",
        ],
        "feature_list_version": config.feature_list_version,
        "dataset_version": config.dataset_version,
        "eval_population": config.eval_population,
    }
    (output / "MANIFEST.json").write_text(json.dumps(manifest, indent=2))

    print(json.dumps(manifest, indent=2))
    print(f"Package: {output}")


if __name__ == "__main__":
    main()
