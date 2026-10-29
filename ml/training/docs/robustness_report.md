# Temporal + Destination-Disjoint Robustness — Role 4

**Model:** XGBoost, contract protocol, serving-consistent balances  
**Conformal:** Mondrian 99%; **R5:** 500,000 (V2.2 provisional)

## Splits

| Split | Train rows | Train fraud rate | Test rows | Test fraud rate | Notes |
|---|---:|---:|---:|---:|---|
| primary_random | 225,407 | 2.899% | 56,352 | 2.900% |  |
| temporal | 224,198 | 1.753% | 57,561 | 7.361% | steps 1–355 → 356–743 |
| destination_disjoint | 225,541 | 2.909% | 56,218 | 2.860% | 161,408 train / 40,353 test destinations; overlap 0 |

## Test metrics

| Split | ROC-AUC | PR-AUC | F1 | Precision | Recall | Hard recall | Rule recall | Coverage legit | Coverage fraud | Review % | Missed frauds |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| primary_random | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0.9810 | 99.10% | 98.96% | 1.354% | 0 |
| temporal | 1.0000 | 1.0000 | 0.9999 | 1.0000 | 0.9998 | 0.9905 | 0.9752 | 99.25% | 97.92% | 1.093% | 0 |
| destination_disjoint | 1.0000 | 1.0000 | 0.9997 | 0.9994 | 1.0000 | 1.0000 | 0.9838 | 98.99% | 98.94% | 1.329% | 0 |

## R1–R6 decision mix (R5 = 500,000)

| Split | R3 rejected | R4 model-uncertain | R5 amount-high | R6 approved | Review | Model-driven | Rule-driven | Frauds caught / missed | Legit in R3 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| primary_random | 2.869% | 0.903% | 0.451% | 95.777% | **1.354%** | 0.903% | 0.451% | 1634/1634 (missed 0) | 0 |
| temporal | 7.208% | 0.844% | 0.248% | 91.699% | **1.093%** | 0.844% | 0.248% | 4237/4237 (missed 0) | 0 |
| destination_disjoint | 2.830% | 1.010% | 0.318% | 95.841% | **1.329%** | 1.010% | 0.318% | 1608/1608 (missed 0) | 0 |

## Notes

- **Temporal** is the drift check: later PaySim steps have a much higher fraud rate and lower volume.
- **Destination-disjoint** is the generalization check: the test receivers are unseen; sender-disjoint
  is trivial on PaySim (99.85% of senders appear once).
- The app-valid filter (`amount <= sender_old_balance`) is a biased serving proxy; the primary
  random split is in `conformal_decision_report.md`.
- The app-valid hard subset is small (~31 frauds per test); treat hard-recall differences as noisy.
- R5 500,000 is rule-driven; the review rate can move under drift even if the model is stable.
