# Serving Handoff — Role 4 → Role 5

**Status:** Ready for integration · **Date:** 1 November 2026
**Source branch:** `feat/role4-paysim-ml-setup` @ `7fe90f4` (main merged; code state `17bd5c8`)
**Author / owner:** ML Training (Role 4) · **Consumer:** ML Serving (Role 5), DevOps (Role 3)
**Companion:** `TEAM_DECISIONS_ROLE4.md` (open product/contract decisions)

---

## 0. TL;DR

Role 4 delivers a trained XGBoost pipeline, its Mondrian-conformal config, a
model card, a six-case parity fixture, and PCA/t-SNE/UMAP JSON. Role 5 owns the
FastAPI service **and the MLflow tracking server / registry / artifact store**;
Role 3 owns the infrastructure those run on. Once Role 5 has a team MLflow URI
and a reachable `/predict`, Role 4 runs the end-to-end parity check and Phase 9
load tests.

**Two hard requirements before building the serving image:**

1. `xgboost==2.1.4` — **not** `2.1.3`. XGBoost 2.1.3 raises
   `'super' object has no attribute '__sklearn_tags__'` on
   `predict_proba` with scikit-learn 1.6.1.
2. `sqlalchemy==2.0.36` — SQLAlchemy 2.1.x removed
   `FallbackAsyncAdaptedQueuePool`, which MLflow 2.16 imports for
   sqlite-backed tracking/registry (used by the serving test suite).

Both are already pinned in `ml/requirements.txt` on this branch.

**Do not merge Role 5's current `ml/common` yet.** The current Role 5 branch
(`3734d93`, commit `22d179a`) changed to **2 transaction types / 11 features**,
while V2.2, the new conventions, and this model use **5 types / 14 features**.
The unmodified current serving suite fails 2 parity tests against this model
(23/25 pass). See §1.5 and `TEAM_DOCS_DRIFT_REPORT.md`.

---

## 1. Ownership boundary

| Area | Owner | Notes |
|---|---|---|
| Trained pipeline, preprocessing, conformal config, metrics, feature list, model card, parity fixture, viz JSON | **Role 4** | Delivered in this branch / package |
| FastAPI `/predict`, `/model-info`, `/viz`, health, serving-side conformal set, parity test | **Role 5** | Loads the artifact from MLflow |
| MLflow server, backend store, artifact store (MinIO/S3) | **Role 3** | `docs/conventions.md` §1; V2.2 §2.2 says “ML Serving + DevOps/MLOps” |
| Model registration, `@production` alias, registry usage | **Role 5** (Role 4 supports) | Role 4 can re-log from the training branch |
| Docker/K8s, HPA, monitoring, secrets | **Role 3** | Serving image is built by Role 5 |
| Phase 9 load tests | **Role 4** | Needs a running endpoint + cluster access |

The local `mlruns/` registry used during development is **not** the handoff
registry. It exists only to prove the logging/alias/loading path. The team
MLflow server is the source of truth.

---

## 1.5. Stop: two contract blockers before integration

The 1 Nov pull of `origin/main` and `origin/feat/role5-mlops` exposed two
blockers that are **not** Role 4 model bugs. Resolve them before merging
`ml/common` or running the serving CI.

### A. 11 vs 14 features

- Role 5 commit `22d179a` sets `TRANSACTION_TYPES = ["CASH_OUT", "TRANSFER"]`
  → **11** transformed columns and a 2-value `TransactionType` enum.
- V2.2 §17.1 says ML Serving **accepts all five** types; the new
  `docs/conventions.md` says the model is **trained on all five** (only app
  traffic is limited to two).
- Our served model is **14** columns (9 numeric + 5 one-hot).
- With our `ml/common` overlaid on current Role 5, **23/25** serving tests pass;
  the 2 failures assert 11 columns:
  `assert (5, 14) == (5, 11)`.

**Recommended fix:** revert Role 5 to five categories / 14 features. If the
team prefers 11, Role 4 must retrain/recalibrate/repack and V2.2 §17.1, the
OpenAPI enum, and the parity fixture must change together.

### B. `docs/conventions.md` §4 is not the V2.2/OpenAPI contract

The new conventions defines a flat request (`transaction_id` + six fields) and
a flat response (`prediction`, `prediction_set`, `model_version`, ...).
V2.2 §17.1/17.2 and the OpenAPI define the nested request
(`schema_version`, `request_id`, `features{}`) and nested response
(`action`, `uncertainty{}`, `model{}`, `explanations.contribution`,
`inference_ms`). Role 5's FastAPI and our parity fixture follow V2.2/OpenAPI.

**Recommended fix:** treat V2.2 + OpenAPI as normative and rewrite conventions
§4. Do not build Risk against the flat shape.

Both are tracked in `TEAM_DECISIONS_ROLE4.md` (D13/D14) and
`TEAM_DOCS_DRIFT_REPORT.md`.

---

## 2. Delivered artifacts

All paths are relative to the repository root.

| Artifact | Path | Purpose |
|---|---|---|
| Serving package | `ml/training/package/` | Everything Role 5 needs in one folder |
| ├─ Model card | `ml/training/package/model_card.md` | Intended use, metrics, limitations |
| ├─ Metrics summary | `ml/training/package/metrics_summary.json` | Config + validation metrics |
| ├─ Conformal config | `ml/training/package/uncertainty_config.json` | 10 raw / 14 transformed features |
| ├─ Parity fixture | `ml/training/package/parity_cases.json` | 6 request/response cases |
| ├─ Feature list | `ml/training/package/feature_list_v1.md` | Frozen v1.2 contract |
| └─ Manifest | `ml/training/package/MANIFEST.json` | File list, model path, versions |
| Viz JSONs | `ml/visualization/data/{pca,tsne,umap}.json` | 2,000 points each |
| Training config | `ml/training/configs/benchmark.yaml` | XGBoost hyper-parameters |
| Final config (canonical) | `ml/training/docs/uncertainty_config.json` | Same content as package copy |
| Contract modules | `ml/common/{artifact_contract,schema,preprocessing}.py` | Shared by training and serving |

The trained pipeline itself is delivered through MLflow
(`models:/fraud-detector@production`), not as a committed binary. The local
joblib at `ml/data/processed/final_contract_model.joblib` is git-ignored and
is only a fallback.

---

## 3. Model contract

- **Algorithm:** `XGBClassifier` (300 trees, depth 6, `hist`).
- **Pipeline steps:** `preprocessor` → `classifier` (exact names).
- **Input:** 10 engineered columns (`FEATURE_COLUMNS`):
  `type`, `amount`, `sender_old_balance`, `sender_new_balance`,
  `receiver_old_balance`, `receiver_new_balance`, `balance_drain_ratio`,
  `receiver_gain_ratio`, `sender_zero_after`, `amount_equals_old_balance`.
- **Transformed signature:** 14 columns (`EXPECTED_TRANSFORMED_FEATURES`):
  the 9 numeric columns + `type_{CASH_IN,CASH_OUT,DEBIT,PAYMENT,TRANSFER}`.
  The encoder is pinned to all five types even though training only sees
  `TRANSFER`/`CASH_OUT`.
- **Request contract:** the six fields in `TransactionFeatures`; the service
  maps them through `ml.common.preprocessing.build_features` (idempotent for
  PaySim and contract-named frames).
- **Serving flow:** `build_features` → `pipeline.predict_proba` →
  `prediction_set` from the config.

```python
import mlflow.sklearn
from ml.common.artifact_contract import UncertaintyConfigContract
from ml.common.preprocessing import build_features

model = mlflow.sklearn.load_model("models:/fraud-detector@production")
config = UncertaintyConfigContract.from_dict(config_dict)  # from the run artifact
features = build_features(contract_frame)                  # 10 columns
p_fraud = float(model.predict_proba(features)[:, 1][0])
```

The preprocessor validates `feature_names_in_ == FEATURE_COLUMNS`; a mismatch
must fail at load time.

---

## 4. Conformal semantics (must match exactly)

Given `p = P(fraud)`:

| Condition | Prediction set | Action | Uncertainty score |
|---|---|---|---|
| `p <= q_hat_legit` | `["legit"]` | `ALLOW` unless score ≥ 0.50 → `HUMAN_REVIEW` | normalized entropy |
| `1 - p <= q_hat_fraud` | `["fraud"]` | `BLOCK` | normalized entropy |
| both conditions | `["legit", "fraud"]` | `HUMAN_REVIEW` | normalized entropy |
| neither | `[]` | `HUMAN_REVIEW` | `max(entropy, 0.85)` |

- `entropy = -[p log2 p + (1-p) log2 (1-p)]`, clipped to `[0, 1]`.
- `fraud_probability` and `uncertainty_score` are rounded to **6 decimals**.
- The empty-set floor of **0.85** is part of the serving contract and is
  exercised by `high_amount_legit` in the parity fixture.
- The config carries `q_hat_fraud = 0.0001049041748046875`,
  `q_hat_legit = 4.517877459875308e-05`, `high_uncertainty_score_threshold =
  0.50`, `confidence_level = 0.99`.

This is the behavior implemented by the Role 5 branch's
`TrainedModelPredictor._compute_conformal_set`; Role 4's package generator now
mirrors it exactly.

---

## 5. Parity fixture

`ml/training/package/parity_cases.json` contains six `POST /predict` requests
with expected responses. All values are from the final 3.11 model.

| Case | `fraud_probability` | `prediction_set` | `action` | `uncertainty_score` |
|---|---:|---|---|---:|
| `legit_partial_transfer` | 0.000004 | `["legit"]` | `ALLOW` | 0.000075 |
| `fraud_full_drain` | 0.999997 | `["fraud"]` | `BLOCK` | 0.000063 |
| `high_amount_legit` | 0.000057 | `[]` | `HUMAN_REVIEW` | 0.850000 |
| `cash_out_withdrawal` | 0.000005 | `["legit"]` | `ALLOW` | 0.000096 |
| `fraud_full_drain_1m` | 0.999998 | `["fraud"]` | `BLOCK` | 0.000032 |
| `small_partial_transfer` | 0.000005 | `["legit"]` | `ALLOW` | 0.000100 |

**How to run:** POST each `case["request"]` to `/predict` and compare
`fraud_probability`, `uncertainty.prediction_set`, `action`, and
`uncertainty.score`. Treat a difference of more than `1e-6` (after rounding)
as a failure. The fixture also covers all three actions and the empty-set
review path.

**Verified on 1 Nov:** Role 4 overlaid its `ml/common/` onto the Role 5 branch
and ran:

- the full Role 5 serving suite: **25/25 passed**;
- the six parity cases through `TestClient` against
  `models:/fraud-detector@production`: **6/6 exact**, `max |delta| = 0.0`;
- `/model-info`: model `fraud-detector` v1, 6 contract + 4 derived features;
- `/viz/{pca,tsne,umap}`: HTTP 200, 2,000 points each.

This is evidence that the artifact and the serving contract are compatible;
Role 5 should repeat it in its own environment after registration.

---

## 6. MLflow / MLOps setup checklist (Role 3 hosts; Role 5 registers)

`docs/conventions.md` assigns the MLflow server to Role 3; Role 5 owns model
registration/loading and the FastAPI service. V2.2 §2.2 calls it shared
“ML Serving + DevOps/MLOps”. The list is the minimum needed for Role 4 to run
Phase 9.

### 6.1 Server and stores

- Tracking server reachable (HTTP), e.g. `http://mlflow:5000`.
- Backend store: Postgres recommended (sqlite is fine only for local tests).
- Artifact store: MinIO/S3; set `MLFLOW_S3_ENDPOINT_URL`,
  `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`.
- Pin `sqlalchemy==2.0.36` in the server/test environment.
- `mlflow==2.16.2` (training) / `mlflow-skinny==2.16.2` (serving image).

### 6.2 Register the champion

From the training branch, with the team URI:

```bash
python -m ml.training.scripts.run_conformal \
  --model xgb --confidence 0.99 --r5 500000 --r5-alt 324610 \
  --log-mlflow --mlflow-tracking-uri http://<team-mlflow>:5000
```

This logs the pipeline at artifact path `model`, the companion
`uncertainty_config.json` at the run root, the required metrics and tags, and
promotes the version to `@production`. Verify:

```python
from mlflow.tracking import MlflowClient
client = MlflowClient("http://<team-mlflow>:5000")
mv = client.get_model_version_by_alias("fraud-detector", "production")
print(mv.version, mv.run_id)
```

Required logged metrics: `roc_auc`, `pr_auc`, `f1`, `precision`, `recall`,
`mcc`, `brier_score`, `expected_review_rate`, `inference_p95_ms`.
Required tags: `algorithm`, `dataset_version`, `git_sha`, `seed`.

### 6.3 Serving environment

| Variable | Value |
|---|---|
| `MLFLOW_TRACKING_URI` | team server URI |
| `MODEL_NAME` | `fraud-detector` |
| `MODEL_ALIAS` | `production` |
| `VIZ_DATA_DIR` | `/app/ml/visualization/data` (or mounted path) |
| `STARTUP_LOAD_ENABLED` | `true` |

Smoke checks: `GET /health/live`, `GET /health/ready`, `GET /model-info`,
then the parity fixture.

### 6.4 Artifact layout

```
<run>/
├── model/                     # MLflow sklearn model (cloudpickle)
│   ├── MLmodel
│   └── ...
└── uncertainty_config.json    # companion config at the run root
```

Do not move `uncertainty_config.json` under `model/`; the Role 5 loader
downloads it from the run root.

---

## 7. Dependency pins and known traps

| Package | Pin | Reason |
|---|---|---|
| `xgboost` | **2.1.4** | 2.1.3 incompatible with sklearn 1.6.1 |
| `scikit-learn` | 1.6.1 | Serving/training parity |
| `numpy` | 1.26.4 | Serving pin |
| `pandas` | 2.2.3 | Serving pin |
| `scipy` | 1.14.1 | Serving pin |
| `mlflow` | 2.16.2 | Training (full) |
| `mlflow-skinny` | 2.16.2 | Serving image |
| `sqlalchemy` | **2.0.36** | MLflow 2.16 + sqlite test store |
| `pyarrow` | 17.0.0 | MLflow 2.16 requires `<18` |
| `joblib` | 1.4.2 | Serialization |
| Python | **3.11** | Serving image base |

Additional traps:

- **Do not** re-fit the preprocessor on serving data. Load the fitted
  pipeline; `build_features` computes only deterministic derived columns.
- **Do not** change the five one-hot categories. A 2-category encoder produces
  11 columns; the current Role 5 branch does exactly that (D14). The model and
  the loader require the 14-column signature.
- **Do not** edit `uncertainty_config.json` by hand; regenerate it with
  `run_conformal`.
- The MLflow model signature documents the **10 engineered inputs**, not the
  six request fields. Serving builds those 10 columns before calling the
  pipeline; do not rely on the signature for request validation.

---

## 8. Visualization handoff

`ml/visualization/data/{pca,tsne,umap}.json` follow the Role 5
`EmbeddingVizResponse` schema:

```json
{
  "schema_version": "1.0",
  "method": "pca",
  "n_points": 2000,
  "generated_at": "...",
  "points": [
    {
      "x": 0.1, "y": -0.2,
      "true_label": 0, "predicted_label": 0,
      "uncertain": false, "error": false,
      "type": "TRANSFER", "amount": 1250.5,
      "balance_drain_ratio": 0.25
    }
  ]
}
```

The serving default cap is 2,000 points; the files match it. If the conception
later requires 5–10k, regenerate with
`python -m ml.visualization.export_embeddings --sample-size 5000` and let the
endpoint downsample.

---

## 9. What Role 4 needs back to start Phase 9

1. Team MLflow URI and confirmation that `fraud-detector@production` resolves.
2. A reachable FastAPI endpoint (local Docker is enough for the first smoke)
   with `/health/ready` returning 200 and `/model-info` showing model vN.
3. Confirmation that the six parity cases pass in the Role 5 environment.
4. Cluster access + gateway rate-limit configuration for the Locust runs, or a
   decision to run the first load test against the local Docker stack.
5. The final R5 threshold and full-drain policy (see
   `TEAM_DECISIONS_ROLE4.md`), because both change the expected review share
   used in the load-test assertions.

Until (1)–(3), Role 4 will not claim the serving integration is complete.

---

## 10. Verification log (fresh, 1 Nov 2026)

| Check | Result |
|---|---|
| Role 4 unit/integration tests | **31/31 passed** (`ml/.venv/bin/python -m pytest ml/ -q`) |
| Role 5 serving suite, **pre-`22d179a`** (14-feature common) | **25/25 passed** |
| Role 5 serving suite, **current** (`3734d93`, 11-feature tests) | **23/25 passed**; 2 expected failures: 11 vs 14 features |
| Training→MLflow→FastAPI parity (14-feature common overlaid) | **6/6 cases**, `max |delta| = 0.0` |
| `/model-info` | model v1, 6 contract + 4 derived features |
| `/viz/{method}` | 200, 2,000 points each |
| MLflow required metrics/tags | none missing |
| Local registry | `fraud-detector` v1 `@production`, run `ba69a008b819403dac7fca0867317922` |
| Branch | `feat/role4-paysim-ml-setup` @ `7fe90f4` (code `17bd5c8`; main merged) |

The serving-suite runs used temporary worktrees of `origin/feat/role5-mlops`
with Role 4's `ml/common/` copied in. The 25/25 result is the **pre-`22d179a`**
branch; the current branch is 23/25 because its tests assert 11 features. The
E2E parity run also used the overlaid 14-feature common, so it proves the app
can load this model once D14 is resolved — not that the current branch is
already compatible.

---

## 11. Commands Role 4 will use

```bash
# regenerate the champion + config (team MLflow)
python -m ml.training.scripts.run_conformal \
  --model xgb --confidence 0.99 --r5 500000 --r5-alt 324610 \
  --log-mlflow --mlflow-tracking-uri "$MLFLOW_TRACKING_URI"

# rebuild the handoff package after a model/config change
python -m ml.training.scripts.package_model

# rebuild the viz JSON
python -m ml.visualization.export_embeddings

# full local test suite
ml/.venv/bin/python -m pytest ml/ -q
```
