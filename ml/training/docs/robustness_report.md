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
| primary_random | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0.9810 | 99.07% | 98.96% | 1.322% | 0 |
| temporal | 1.0000 | 1.0000 | 0.9996 | 1.0000 | 0.9993 | 0.9714 | 0.9752 | 99.52% | 98.47% | 0.804% | 0 |
| destination_disjoint | 1.0000 | 1.0000 | 0.9997 | 0.9994 | 1.0000 | 1.0000 | 0.9838 | 98.97% | 98.94% | 1.290% | 0 |

## R1–R6 decision mix (R5 = 500,000)

| Split | R3 rejected | R4 model-uncertain | R5 amount-high | R6 approved | Review | Model-driven | Rule-driven | Frauds caught / missed | Legit in R3 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| primary_random | 2.869% | 0.935% | 0.387% | 95.808% | **1.322%** | 0.935% | 0.387% | 1634/1634 (missed 0) | 0 |
| temporal | 7.248% | 0.554% | 0.250% | 91.948% | **0.804%** | 0.554% | 0.250% | 4237/4237 (missed 0) | 0 |
| destination_disjoint | 2.830% | 1.033% | 0.256% | 95.880% | **1.290%** | 1.033% | 0.256% | 1608/1608 (missed 0) | 0 |

## Notes

- **Temporal** is the drift check: later PaySim steps have a much higher fraud rate and lower volume.
- **Destination-disjoint** is the generalization check: the test receivers are unseen; sender-disjoint
  is trivial on PaySim (99.85% of senders appear once).
- The app-valid filter (`amount <= sender_old_balance`) is a biased serving proxy; the primary
  random split is in `conformal_decision_report.md`.
- The app-valid hard subset is small (~31 frauds per test); treat hard-recall differences as noisy.
- R5 500,000 is rule-driven; the review rate can move under drift even if the model is stable.
