# Conformal + Decision-Level Evaluation — Role 4

**Model:** XGBClassifier (contract protocol, serving-consistent balances)  
**Confidence:** 99% (Mondrian, class-conditional)  
**Parent population:** app-valid `TRANSFER` + `CASH_OUT`  
**R5:** base 500,000; alternative 324,610

## Data

| Split | Rows | Frauds | Fraud rate |
|---|---:|---:|---:|
| Fit | 180,325 | 5,227 | 2.899% |
| Calibration | 45,082 | 1,307 | 2.899% |
| Test | 56,352 | 1,634 | 2.900% |

The app computes both new balances, so fit/calibration/test use `new = old ± amount`;
the raw PaySim view is reported as a sensitivity.

## Conformal thresholds

- q̂_fraud = **0.000118**
- q̂_legit = **0.000053**

## Test coverage and set size

| Metric | Value |
|---|---:|
| Coverage — legit | 99.10% |
| Coverage — fraud | 98.96% |
| Average set size | 0.991 |
| Empty / singleton / both | 509 / 55,843 / 0 |

## Model metrics (test, 0.5 threshold)

| Metric | Value |
|---|---:|
| ROC-AUC | 1.0000 |
| PR-AUC | 1.0000 |
| F1 | 1.0000 |
| Precision | 1.0000 |
| Recall | 1.0000 |
| MCC | 1.0000 |
| Brier | 0.000000 |
| Hard-subset rows / frauds | 54,749 / 31 |
| Hard-subset recall | 1.0000 |
| Rule baseline recall | 0.9810 |
| Inference p95 | 12.932 ms |

**Read this as the PaySim ceiling:** the model is the drain rule plus the hard subset;
the decision mix below is the meaningful result.

## Decision mix — R1–R6

| R5 threshold | R3 rejected | R4 model-uncertain | R5 amount-high | R6 approved | Review | Model-driven | Rule-driven | Frauds caught / missed | Legit in R3 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 500,000 | 2.869% | 0.903% | 0.451% | 95.777% | **1.354%** | 0.903% | 0.451% | 1634/1634 (missed 0) | 0 |
| 324,610 | 2.869% | 0.903% | 3.003% | 93.225% | **3.906%** | 0.903% | 3.003% | 1634/1634 (missed 0) | 0 |

R5 is **rule-driven**: every transfer is scored first; a confident-legit result above
the threshold goes to review (`AMOUNT_HIGH`). R4 is **model-driven** (`MODEL_UNCERTAIN`).
R2 (`SERVICE_DEGRADED`) and R1b (`TYPE_NOT_SCORED`) are not simulated; the app only
creates TRANSFER/CASH_OUT and the ML service is assumed available.

**R5 validation:** 500,000 → **1.354%** total review (0.903% model + 0.451% rule), all
1,634 frauds caught, 0 legitimate rejected. 324,610 → **3.906%** total review
(0.903% + 3.003%), same frauds. Both are ≤5%; 500,000 is conservative, 324,610 uses
more of the review budget.

**Coverage note:** 17/1,634 frauds fall outside the prediction set (coverage 98.96%,
close to the 99% target); all 17 are empty-set R4 review, so no fraud is auto-approved.
If strict 99% coverage is required, raise the confidence to 99.5% or enlarge the
calibration set.

## Raw-PaySim sensitivity (same model/q-hats)

| View | Coverage legit | Coverage fraud | R4 % | R5 % | Review % |
|---|---:|---:|---:|---:|---:|
| Serving-consistent | 99.10% | 98.96% | 0.903% | 0.451% | 1.354% |
| Raw PaySim | 99.12% | 98.04% | 0.907% | 0.447% | 1.354% |

**Full-drain note:** a legitimate whole-balance transfer is flagged `{fraud}` and rejected by R3.
V2.2 uses this as the demo `REJECTED` case; the legitimate-user UX remains open.

**Artifact:** `ml/training/docs/uncertainty_config.json`; model `ml/data/processed/final_contract_model.joblib` (git-ignored).