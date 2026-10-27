# MLflow Model Artifact & Logging Contract (Person 2 ↔ Person 3)

**Status:** Frozen v1.0  
**Owners:** Role 4 / Person 2 (ML Training) & Role 5 / Person 3 (MLOps & ML Serving)  
**Code Reference:** [`ml/common/artifact_contract.py`](../ml/common/artifact_contract.py)

---

## 1. Registry Format Decision

We use **Format B (`sklearn.pipeline.Pipeline` + `uncertainty_config.json`)** as the canonical MLflow Registry contract:

1. **`model/` (MLflow `sklearn` flavor):**
   - A fitted `sklearn.pipeline.Pipeline` whose first step is `ml.common.preprocessing.build_preprocessor()` (`ColumnTransformer` over the 10 columns produced by `build_features()`) and whose final step is the calibrated classifier exposing `.predict_proba(X)`.
   - Logged via:
     ```python
     mlflow.sklearn.log_model(
         sk_model=pipeline,
         artifact_path="model",
         registered_model_name="fraud-detector",
     )
     ```
2. **`uncertainty_config.json` (Companion Run Artifact):**
   - Logged in the **same MLflow run** via:
     ```python
     mlflow.log_dict(uncertainty_config.to_dict(), "uncertainty_config.json")
     ```
   - Contains the calibrated Mondrian / split-conformal quantile thresholds (`q_hat_fraud`, `q_hat_legit`), `confidence_level` (`0.95`), `target_review_rate` (`0.05`), `feature_names` signature, `algorithm`, `trained_at`, and `metrics_summary`.

---

## 2. How Conformal Prediction Sets Are Computed at Serving Time

Given calibrated fraud probability $p_{\text{fraud}} = P(Y = 1 \mid x)$ and legitimate probability $p_{\text{legit}} = 1 - p_{\text{fraud}}$:
- Non-conformity scores:
  - $s_{\text{fraud}}(x) = 1 - p_{\text{fraud}}$
  - $s_{\text{legit}}(x) = 1 - p_{\text{legit}} = p_{\text{fraud}}$
- Inclusion rules using thresholds $\hat{q}_{\text{fraud}}, \hat{q}_{\text{legit}} \in (0, 1]$ from `uncertainty_config.json`:
  - `"legit"` $\in \Gamma(x) \iff p_{\text{fraud}} \le \hat{q}_{\text{legit}}$
  - `"fraud"` $\in \Gamma(x) \iff 1 - p_{\text{fraud}} \le \hat{q}_{\text{fraud}} \iff p_{\text{fraud}} \ge 1 - \hat{q}_{\text{fraud}}$
- Resulting `prediction_set` $\Gamma(x) \subseteq \{\text{"legit"}, \text{"fraud"}\}$:
  - `["legit"]` $\rightarrow$ `action = "ALLOW"`
  - `["fraud"]` $\rightarrow$ `action = "BLOCK"`
  - `["legit", "fraud"]` $\rightarrow$ `action = "HUMAN_REVIEW"` (metric reason: `ambiguous_set`)
  - `[]` $\rightarrow$ `action = "HUMAN_REVIEW"` (metric reason: `empty_set`)

---

## 3. Experiment, Alias & Metric Naming Contract

| Item | Canonical Value |
| :--- | :--- |
| **Experiment Name** | `paysim-fraud-benchmark` |
| **Registered Model Name** | `fraud-detector` |
| **Production Alias** | `production` (`models:/fraud-detector@production`) |
| **Staging Alias** | `staging` (`models:/fraud-detector@staging`) |
| **Required Logged Metrics** | `roc_auc`, `pr_auc`, `f1`, `precision`, `recall`, `mcc`, `brier_score`, `expected_review_rate`, `inference_p95_ms` |
| **Required Run Tags** | `algorithm`, `dataset_version`, `git_sha`, `seed` |
