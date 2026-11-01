# Model Card — `fraud-detector`

**Generated:** 2026-11-01T00:34:28.737312+00:00 · **Owner:** ML Training (Role 4)
**Algorithm:** XGBClassifier · **Contract:** feature list v1.2
**Conformal:** mondrian_conformal, 99% confidence
**R5 threshold:** 500,000

## Intended use

Transaction risk scoring for the wallet's `TRANSFER` and `CASH_OUT` flows,
plus human review under the Risk R1–R6 policy. **Synthetic PaySim data only;
not validated for real money or real-world fraud.**

## Data and features

- App-valid, in-scope population: TRANSFER + CASH_OUT, `amount > 0`,
  `amount <= sender_old_balance`; the app computes both new balances.
- Six contract fields + four derived features; ML Serving accepts all five
  type values; the app sends TRANSFER/CASH_OUT.
- Feature list v1.2; 10 input
  columns; 14 transformed columns.

## Validation metrics (app-valid test)

| Metric | Value |
|---|---:|
| ROC-AUC | 1.0000 |
| PR-AUC | 1.0000 |
| F1 | 1.0000 |
| Precision | 1.0000 |
| Recall | 1.0000 |
| MCC | 1.0000 |
| Brier | 0.00000033 |
| Hard-subset recall | 1.0000 |
| Expected review rate | 1.322% |
| Model-uncertain rate | 0.935% |
| Amount-high rate | 0.387% |
| Inference p95 | 4.2 ms |

## Decision policy

R3 `{fraud}` → reject; R4 `{legit,fraud}`/`[]` → review; R5 `{legit}` +
amount ≥ threshold → review; R6 `{legit}` → approve. The R5 share is
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
   coverage is 98.47%, but all uncovered frauds are R4 review.
5. **No sender history** (99.85% unique senders) and a single fraud pattern.
6. **Receivers:** destination-disjoint evaluation is clean; the model is not
   validated on unseen real-world mule behaviour.

## Handoff

- MLflow: `models:/fraud-detector@production`, companion `uncertainty_config.json`.
- Serving path: `build_features` (contract-named) → `pipeline.predict_proba` →
  `prediction_set` from the config.
- Parity fixture: `parity_cases.json`.
