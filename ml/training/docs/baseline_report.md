# Logistic Regression Baseline — full data

**Generated:** 2026-10-21 · **Script:** `ml/training/scripts/run_baseline.py`
**Model:** LogisticRegression (lbfgs, max_iter=1000, no class weights)
**Preprocessing:** shared `ml/common/preprocessing.py` (14 features: 9 scaled numeric + 5 one-hot `type`)

## Split (primary protocol)

| Split | Rows | Fraud rate |
|---|---|---|
| Fit | 4,072,076 | 0.1291% |
| Calibration | 1,018,020 | 0.1291% |
| Test | 1,272,524 | 0.1291% |

## Test metrics — threshold 0.5

| Metric | Value |
|---|---|
| Accuracy | 1.0000 |
| Precision | 1.0000 |
| Recall | 0.9921 |
| F1 | 0.9960 |
| ROC-AUC | 0.9990 |
| PR-AUC | 0.9976 |
| MCC | 0.9960 |
| Brier | 0.000007 |
| Predicted positive rate | 0.128% |

Confusion matrix at 0.5: **TN 1,270,881 · FP 0 · FN 13 · TP 1,630**

Reference — always predicting "legitimate" gives accuracy 0.9987, recall 0, F1 0: **accuracy alone is meaningless here**.

## Calibration-selected operating point

Best F1 threshold on the **calibration** set: **0.4074**.

| Metric | Value |
|---|---|
| Precision | 1.0000 |
| Recall | 0.9976 |
| F1 | 0.9988 |
| MCC | 0.9988 |

## Preliminary ablation (Logistic Regression only)

| Feature set | Features | ROC-AUC | PR-AUC | F1 | Recall |
|---|---|---|---|---|---|
| Full contract | 14 | 0.9990 | 0.9976 | 0.9988 | 0.9976 |
| No new balances | 9 | 0.9498 | 0.2934 | 0.3541 | 0.2928 |
| Amount only | 6 | 0.8903 | 0.0094 | 0.0361 | 0.0572 |

The full contract model is near-perfect because the new-balance/equality features encode the simulator's drain rule; without them the task becomes genuinely hard. The Phase-4 benchmark will repeat this ablation for all five algorithms.

## Inference timing

| Measure | Value |
|---|---|
| Batch (amortised) | 0.031 µs/row |
| Single row p50 | 0.086 ms |
| Single row p95 | 0.091 ms |

## Figures

![Confusion matrix](figures/baseline_confusion_matrix.png)
![ROC curve](figures/baseline_roc_curve.png)
![PR curve](figures/baseline_pr_curve.png)
![Calibration curve](figures/baseline_calibration.png)
![Probability distribution](figures/baseline_probability_distribution.png)

## Interpretation

- PaySim's near-deterministic drain rule makes a linear baseline very strong; high scores are expected and are a **dataset property**, not evidence of real-world capability.
- The calibration curve and Brier score are reported as-is; class weighting/resampling is evaluated in the Phase 4 benchmark, not hidden in the baseline.
- The threshold 0.5 is arbitrary under 0.129% prevalence; the calibration-selected threshold above is a first honest operating point. The final policy (allow/decline/review) will use conformal prediction sets in Phase 6.
- Next: Phase 4 — five algorithms (LR, RF, XGBoost, SVM, MLP), repeated CV × seeds, plus the restricted ablation without new-balance fields.

## Artifacts

- `ml/training/docs/baseline_metrics.json`
- `ml/data/processed/baseline_model.joblib` (git-ignored)
- `ml/training/docs/figures/baseline_*.png`
