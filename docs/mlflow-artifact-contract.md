# MLflow Model Artifact & Logging Contract (Role 4 ↔ Role 5)

**Status:** Frozen v1.2 (Verified E2E in Production Container)  
**Owners:** Role 4 / Person 2 (ML Training) & Role 5 / Person 3 (MLOps & ML Serving)  
**Code References:** [`ml/common/artifact_contract.py`](ml/common/artifact_contract.py), [`ml/pipeline/populate_mlflow.py`](ml/pipeline/populate_mlflow.py), [`ml/pipeline/validate_gate.py`](ml/pipeline/validate_gate.py), [`ml/pipeline/promote_model.py`](ml/pipeline/promote_model.py)

---

## 1. Registry Format & MLflow 2.16.2 Compatibility Contract

We use **Format B (`sklearn.pipeline.Pipeline` + `uncertainty_config.json` + `statistical_validation.json`)** as the canonical MLflow Registry contract:

1. **`model/` (MLflow `sklearn` flavor, `cloudpickle` serialization):**
   - A fitted `sklearn.pipeline.Pipeline` whose first step is `ml.common.preprocessing.build_preprocessor()` (`ColumnTransformer` over the 10 columns produced by `build_features()`, outputting the 14 transformed features: 9 numeric + 5 one-hot) and whose final step is the calibrated `XGBClassifier` exposing `.predict_proba(X)`.
   - **Important MLflow 2.16.2 Server Compatibility Note:** Newer MLflow 3.x clients call `/api/2.0/mlflow/logged-models` inside `mlflow.sklearn.log_model()`, which returns `HTTP 404` against MLflow `v2.16.2` servers. To remain compatible across both MLflow 2.x and 3.x clients, save locally with `cloudpickle` and upload via `mlflow.log_artifacts` + `client.create_model_version` (as implemented in [`ml/pipeline/populate_mlflow.py`](ml/pipeline/populate_mlflow.py)):
     ```python
     with tempfile.TemporaryDirectory(prefix="mlflow_model_") as tmp_dir:
         model_dir = os.path.join(tmp_dir, "model")
         mlflow.sklearn.save_model(
             sk_model=pipeline,
             path=model_dir,
             serialization_format="cloudpickle",
         )
         mlflow.log_artifacts(model_dir, artifact_path="model")

     mv = client.create_model_version(
         name="fraud-detector",
         source=f"{run.info.artifact_uri}/model",
         run_id=run.info.run_id,
     )
     client.set_registered_model_alias("fraud-detector", "candidate", str(mv.version))
     ```
2. **`uncertainty_config.json` (Companion Run Artifact at Run Root):**
   - Logged at the root of the same MLflow run (`mlflow.log_artifact(..., artifact_path="")`).
   - Contains the calibrated Mondrian split-conformal quantile thresholds (`q_hat_fraud = 0.0001049041748046875`, `q_hat_legit = 4.517877459875308e-05`), `confidence_level` (`0.99`), `target_review_rate` (`0.05`), `high_uncertainty_score_threshold` (`0.50`), `feature_names` (10 columns), `transformed_feature_names` (14 columns), `algorithm` (`XGBClassifier`), `trained_at`, and `metrics_summary`.
   - Coupled atomically to the run via the `uncertainty_config_sha256` run tag, verified at load time by both `validate_gate.py` and `ml/serving/model_loader.py`.
3. **`statistical_validation.json` (Companion Run Artifact at Run Root):**
   - Logged at the root of the same MLflow run.
   - Contains the omnibus Friedman test result (`friedman_p = 2.90086e-12 < 0.05`) and pairwise Wilcoxon signed-rank + Holm step-down adjusted p-values (`min_holm_p = 0.00061 < 0.05`).

---

## 2. How Conformal Prediction Sets & Actions Are Computed at Serving Time

Given calibrated fraud probability $p_{\text{fraud}} = P(Y = 1 \mid x)$ and legitimate probability $p_{\text{legit}} = 1 - p_{\text{fraud}}$:

- **Non-conformity scores:**
  - $s_{\text{fraud}}(x) = 1 - p_{\text{fraud}}$
  - $s_{\text{legit}}(x) = 1 - p_{\text{legit}} = p_{\text{fraud}}$
- **Inclusion rules** using thresholds $\hat{q}_{\text{fraud}}, \hat{q}_{\text{legit}} \in (0, 1]$ from `uncertainty_config.json`:
  - `"legit"` $\in \Gamma(x) \iff p_{\text{fraud}} \le \hat{q}_{\text{legit}}$
  - `"fraud"` $\in \Gamma(x) \iff 1 - p_{\text{fraud}} \le \hat{q}_{\text{fraud}} \iff p_{\text{fraud}} \ge 1 - \hat{q}_{\text{fraud}}$
- **Uncertainty score ($H_2$ binary entropy with empty-set floor):**
  - $H_2(p) = -\bigl[p \log_2(p) + (1-p)\log_2(1-p)\bigr] \in [0, 1]$
  - When $\Gamma(x) = \emptyset$, score is floored at $\max(H_2(p), 0.85) = 0.85$.
- **Decision mapping (`prediction_set` $\Gamma(x) \rightarrow \text{action}$):**

| Condition | `prediction_set` $\Gamma(x)$ | `action` | `uncertainty.score` | Prometheus `reason` |
| :--- | :--- | :--- | :--- | :--- |
| $p_{\text{fraud}} \le \hat{q}_{\text{legit}}$ and score $< 0.50$ | `["legit"]` | `ALLOW` | $\text{round}(H_2(p), 6)$ | *(confident)* |
| $1 - p_{\text{fraud}} \le \hat{q}_{\text{fraud}}$ | `["fraud"]` | `BLOCK` | $\text{round}(H_2(p), 6)$ | *(confident)* |
| Both conditions hold | `["legit", "fraud"]` | `HUMAN_REVIEW` | $\text{round}(H_2(p), 6)$ | `ambiguous_set` |
| Neither holds | `[]` | `HUMAN_REVIEW` | `0.85` | `empty_set` |
| Singleton `["legit"]` with score $\ge 0.50$ | `["legit"]` | `HUMAN_REVIEW` | $\text{round}(H_2(p), 6)$ | `high_uncertainty_score` |

---

## 3. Experiment, Alias & Metric Naming Contract

| Item | Canonical Value |
| :--- | :--- |
| **Experiment Name** | `paysim-fraud-benchmark` |
| **Benchmark Comparison Runs** | `benchmark-lr`, `benchmark-rf`, `benchmark-svm`, `benchmark-mlp` (metrics only, not registered in Model Registry) |
| **Champion Run Name** | `champion-xgboost-candidate` |
| **Registered Model Name** | `fraud-detector` |
| **Candidate Alias (logged pre-gate)** | `candidate` (`models:/fraud-detector@candidate`) |
| **Staging Alias (promoted after Gate)** | `staging` (`models:/fraud-detector@staging`) |
| **Production Alias (active serving)** | `production` (`models:/fraud-detector@production`) |
| **Previous Alias (instant rollback)** | `previous` (`models:/fraud-detector@previous`) |
| **Companion Artifacts** | `uncertainty_config.json`, `statistical_validation.json` |
| **Required Logged Metrics** | `roc_auc`, `pr_auc`, `f1`, `precision`, `recall`, `mcc`, `brier_score`, `expected_review_rate`, `inference_p95_ms` |
| **Required Run Tags** | `algorithm`, `dataset_version`, `git_sha`, `seed`, `data_source` (`paysim`; `synthetic` blocked from `@production`), `uncertainty_config_sha256` |
