# MLOps & ML Serving — Operational Runbook & Safe Execution Guide

> **Owner:** Role 5 — MLOps & ML Serving Engineer (`ml/serving/`, `ml/pipeline/`, `infrastructure/mlflow/`)
> **Branch:** `feat/role5-mlops`
> **Target Audience:** All FinTech Team Members (Backend, Frontend, DevOps, Data Science) & Project Evaluators

---

## 1. Overview & Execution Pipeline Schema

This runbook provides the exact step-by-step commands and configuration instructions required to build, launch, populate, promote, and verify the **FinTech Fraud Detection MLOps & ML Serving Stack** safely on any local machine (Windows, Linux, or macOS) or CI runner.

### End-to-End 5-Phase Execution Workflow

```mermaid
flowchart TD
    subgraph P0["Phase 0: Configuration & Prerequisites"]
        ENV[".env Configuration<br/>(Port 5432/5433 & Credentials)"]
        DEPS["Host Python Dependencies<br/>pip install -r ml/requirements.txt"]
    end

    subgraph P1["Phase 1: Container Image Build"]
        BUILD["docker build -t fintech-ml-serving:latest<br/>-f ml/serving/Dockerfile ."]
    end

    subgraph P2["Phase 2: MLflow & Storage Infrastructure"]
        INFRA["docker compose up -d --build<br/>postgres + minio + minio-init + mlflow"]
    end

    subgraph P3["Phase 3: MLflow Pipeline & Quality Gate"]
        POP["1. Seed Registry & Benchmarks<br/>python -m ml.pipeline.populate_mlflow"]
        GATE["2. Validate Quality Gate<br/>python -m ml.pipeline.validate_gate --alias candidate"]
        PROM1["3. Promote to Staging<br/>python -m ml.pipeline.promote_model --from-alias candidate --to-alias staging"]
        PROM2["4. Promote to Production<br/>python -m ml.pipeline.promote_model --from-alias staging --to-alias production"]
        POP --> GATE --> PROM1 --> PROM2
    end

    subgraph P4["Phase 4: Start FastAPI Serving Container"]
        SERVE["docker run -d --name fintech-ml-serving<br/>--network fintech_default -p 8000:8000<br/>Loads @production model from MLflow + MinIO"]
    end

    subgraph P5["Phase 5: End-to-End Verification"]
        VERIFY["Verify /health/ready, /model-info, /predict (6 Golden Cases),<br/>/viz/{pca,tsne,umap}, /metrics"]
    end

    P0 --> P1 --> P2 --> P3 --> P4 --> P5
```

---

## 2. Quick-Reference URLs & Ports Directory

Keep this table handy when running and inspecting the stack locally:

| Service / Endpoint | Local URL | Credentials / Auth | Description |
| :--- | :--- | :--- | :--- |
| **FastAPI Serving Base URL** | http://localhost:8000 | None | Root API endpoint used by Spring Boot (`risk-service`) & React |
| **Swagger UI (Interactive Docs)** | http://localhost:8000/docs | None | Test `/predict`, `/model-info`, `/viz/*` directly in the browser |
| **ReDoc API Documentation** | http://localhost:8000/redoc | None | Clean OpenAPI 3.1.0 reference documentation |
| **OpenAPI JSON Spec** | http://localhost:8000/openapi.json | None | Live OpenAPI schema |
| **Liveness Probe** | http://localhost:8000/health/live | None | Returns `200 OK` (`{"status": "alive"}`) |
| **Readiness Probe** | http://localhost:8000/health/ready | None | Returns `200 OK` when `@production` model is loaded in RAM |
| **Model Metadata** | http://localhost:8000/model-info | None | Active model name, version, alias, threshold, and SHA-256 hash |
| **Prometheus Metrics** | http://localhost:8000/metrics | None | Scraped by Prometheus (`ml_inference_*`, `ml_fraud_*`, `ml_model_*`) |
| **MLflow Tracking & Registry UI** | http://localhost:5000 | None | View experiment `paysim-fraud-benchmark` and model `fraud-detector` |
| **MinIO Web Console (UI)** | http://localhost:9001 | Defined in `.env` (`MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD`) | Browse `mlflow` S3 bucket and inspect `model.pkl` artifacts |
| **MinIO S3 API Endpoint** | http://localhost:9000 | `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | S3-compatible object storage API used by MLflow & boto3 |
| **PostgreSQL Database (Host)** | `localhost:5432` (or `localhost:5433` on Windows) | Defined in `.env` (`POSTGRES_USER` / `POSTGRES_PASSWORD`) | Backend store for MLflow metadata |

---

## 3. Critical Environment Setup (`.env`) & Platform Notes

Before running any Docker or Python command, create your local `.env` file at the repository root by copying `.env.example`:

**Windows (PowerShell):**
```powershell
Copy-Item .env.example .env
```

**Linux / macOS (Bash):**
```bash
cp .env.example .env
```

> [!CAUTION]
> **Never commit `.env` to Git.** It is already ignored in `.gitignore`. Every developer must create their own local `.env` from `.env.example`.

---

### 3.1 Important Note for Windows Users: PostgreSQL Port `5432` vs `5433`

Many Windows developers have a native **PostgreSQL Windows Service** installed locally (e.g., via pgAdmin or PostgreSQL installer) that automatically binds to port `5432` on startup.

If you run `docker compose up -d` while Windows PostgreSQL is occupying port `5432`, Docker will fail with:
`Bind for 0.0.0.0:5432 failed: port is already allocated`

**How to fix this cleanly in `.env`:**
Open `.env` and change `POSTGRES_PORT` from `5432` to `5433`:
```dotenv
POSTGRES_PORT=5433
```

**Why this is 100% safe and requires no other changes:**
- `POSTGRES_PORT` only controls the **host-to-container port mapping** (`0.0.0.0:5433->5432/tcp`).
- Inside the Docker network (`fintech_default`), the `fintech-mlflow` container still connects to `postgres:5432` internally (`MLFLOW_BACKEND_STORE_URI=postgresql://...@postgres:5432/...`), so **do NOT change `5432` inside `MLFLOW_BACKEND_STORE_URI`**.

---

### 3.2 How to Customize Database & MinIO Bucket Credentials

You are free to customize the PostgreSQL and MinIO credentials in your `.env` file, provided you keep the linked variables synchronized:

#### A. Changing MinIO Bucket User & Password
In `.env`, MinIO uses `MINIO_ROOT_USER` and `MINIO_ROOT_PASSWORD` to initialize the server, while MLflow and the Python CLI scripts use `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` to authenticate against MinIO's S3 API. **They must be identical:**

```dotenv
# 1. MinIO Server Credentials (minimum 3 characters for user, 8 characters for password)
MINIO_ROOT_USER=my_custom_minio_admin
MINIO_ROOT_PASSWORD=my_custom_minio_secret_123

# 2. S3 Client Credentials (MUST match MINIO_ROOT_USER and MINIO_ROOT_PASSWORD above!)
AWS_ACCESS_KEY_ID=my_custom_minio_admin
AWS_SECRET_ACCESS_KEY=my_custom_minio_secret_123
```

#### B. Changing PostgreSQL User, Password, or Database Name
If you change `POSTGRES_USER`, `POSTGRES_PASSWORD`, or `POSTGRES_DB` in `.env`, you **must** also update `MLFLOW_BACKEND_STORE_URI` on the line below them so MLflow uses the same credentials:

```dotenv
POSTGRES_USER=my_pg_user
POSTGRES_PASSWORD=my_pg_password
POSTGRES_DB=mlflow_db
POSTGRES_PORT=5433

# MUST match POSTGRES_USER, POSTGRES_PASSWORD, and POSTGRES_DB above (keep port :5432 here!)
MLFLOW_BACKEND_STORE_URI=postgresql://my_pg_user:my_pg_password@postgres:5432/mlflow_db
```

> [!WARNING]
> **Changing Credentials After First Boot:**
> PostgreSQL and MinIO persist their initial credentials inside Docker volumes (`postgres_data` and `minio_data`) the very first time they start. If you change passwords in `.env` *after* you have already started the containers once, you must reset the volumes for the new passwords to take effect:
> ```bash
> docker compose down -v
> docker compose up -d
> ```

---

### 3.3 Why Local Python Dependencies (`ml/requirements.txt`) Are Needed

You might wonder why we install Python libraries locally if MLflow and FastAPI run inside Docker:
- **Docker containers** (`fintech-mlflow` and `fintech-ml-serving`) already have their dependencies baked into their Docker images.
- **Host CLI execution:** When a developer runs `python -m ml.pipeline.populate_mlflow`, `validate_gate`, or `promote_model` from their terminal, Python executes on the **host machine** and talks to `localhost:5000` (MLflow) and `localhost:9000` (MinIO). Therefore, your local Python environment needs `mlflow`, `boto3`, `scikit-learn`, `xgboost`, and `pydantic`.

Install them once in your virtual environment or local Python:
```bash
pip install -r ml/requirements.txt
```

---

## 4. Step-by-Step Execution Guide (Phases 1 to 5)

Run all commands below from the **repository root directory** (`FinTech/`).

---

### Phase 1 — Build the FastAPI ML Serving Docker Image

Build the production serving image (`fintech-ml-serving:latest`) from the repository root context:

```bash
docker build -t fintech-ml-serving:latest -f ml/serving/Dockerfile .
```

Verify the image was created:
```bash
docker images fintech-ml-serving:latest
```

---

### Phase 2 — Start the MLflow & Storage Infrastructure Stack

Start PostgreSQL, MinIO, the MinIO bucket initializer (`minio-init`), and the MLflow Tracking Server:

```bash
docker compose up -d --build postgres minio minio-init mlflow
```

> [!NOTE]
> **About the `pull access denied for fintech-mlflow` message:**
> The very first time you run `docker compose up -d`, Docker Compose checks if a pre-built image named `fintech-mlflow` exists on Docker Hub before building [`infrastructure/mlflow/Dockerfile`](infrastructure/mlflow/Dockerfile) locally. Seeing `! mlflow Warning pull access denied for fintech-mlflow` followed by `Building mlflow` is completely normal Docker behavior and **not an error**. Using `--build` skips the remote check.

Check that all services are healthy:
```bash
docker compose ps -a
```

**Expected Status:**
- `fintech-postgres`: `Up (healthy)`
- `fintech-minio`: `Up (healthy)`
- `fintech-minio-init`: `Exited (0)` *(one-shot job that creates the `s3://mlflow` bucket and exits cleanly)*
- `fintech-mlflow`: `Up (healthy)` on `http://localhost:5000`

---

### Phase 3 — Populate MLflow, Validate Quality Gate, and Promote Model

Because our team uses **local Docker environments** rather than a paid cloud MLflow server, each developer's local PostgreSQL and MinIO start empty. The commands below read Role 4's committed metrics and configuration from `ml/training/package/`, seed your local MLflow registry, validate the quality gate, and promote the model to `@production`.

*(Note: [`ml/pipeline/mlflow_config.py`](ml/pipeline/mlflow_config.py) automatically loads your `.env` file, so you do not need to manually export `AWS_ACCESS_KEY_ID` or `AWS_SECRET_ACCESS_KEY` in your terminal!)*

#### Step 3.1 — Seed MLflow Experiments & Register `@candidate` Model
```bash
python -m ml.pipeline.populate_mlflow
```
**What this does:**
1. Logs the 4 benchmark family runs (`lr`, `rf`, `svm`, `mlp`) into experiment `paysim-fraud-benchmark` using the exact metrics from [`ml/training/package/benchmark_runs.csv`](ml/training/package/benchmark_runs.csv).
2. Packages the calibrated XGBoost champion pipeline + `uncertainty_config.json` (`decision_threshold: 0.786636`) + `parity_cases.json` + `feature_order.json`, uploads them to `s3://mlflow` in MinIO, registers model `fraud-detector` (version `1`), and assigns alias `@candidate`.

#### Step 3.2 — Run the Automated Quality Gate on `@candidate`
```bash
python -m ml.pipeline.validate_gate --alias candidate
```
**What this does:**
- Fetches `fraud-detector@candidate` from MLflow (`http://localhost:5000`).
- Verifies all 4 mandatory thresholds (`test_pr_auc >= 0.80`, `test_recall_at_fpr_1pct >= 0.65`, `test_brier_score <= 0.05`, `test_f1 >= 0.75`) and all 4 required artifacts (`MLmodel`, `uncertainty_config.json`, `parity_cases.json`, `feature_order.json`).
- Outputs a structured JSON report with `"passed": true` and exits with code `0`. *(Note: `validate_gate` is a read-only verifier; it does not change the model alias itself).*

#### Step 3.3 — Promote `@candidate` $\rightarrow$ `@staging`
```bash
python -m ml.pipeline.promote_model --from-alias candidate --to-alias staging
```

#### Step 3.4 — Promote `@staging` $\rightarrow$ `@production`
```bash
python -m ml.pipeline.promote_model --from-alias staging --to-alias production
```
**What this does:**
- Re-verifies the quality gate before moving the alias.
- Archives any previous `@production` version to `@archived` for instant rollback safety.
- Assigns `@production` to `fraud-detector` version `1` and stamps audit tags on the model version.

*(Optional) How to Rollback in an Emergency:*
```bash
python -m ml.pipeline.promote_model --rollback
```

---

### Phase 4 — Run the FastAPI ML Serving Container (`fintech-ml-serving`)

Once `fraud-detector@production` is registered in MLflow, launch the `fintech-ml-serving` container on the `fintech_default` network so it can communicate with `mlflow:5000` and `minio:9000`, and mount the visualization data directory (`ml/visualization/data`) read-only:

**Windows (PowerShell):**
```powershell
docker rm -f fintech-ml-serving 2>$null
docker run -d `
  --name fintech-ml-serving `
  --network fintech_default `
  -p 8000:8000 `
  --env-file .env `
  -e MLFLOW_TRACKING_URI=http://mlflow:5000 `
  -e MLFLOW_S3_ENDPOINT_URL=http://minio:9000 `
  -e MODEL_NAME=fraud-detector `
  -e MODEL_ALIAS=production `
  -v "${PWD}/ml/visualization/data:/app/ml/visualization/data:ro" `
  fintech-ml-serving:latest
```

**Linux / macOS (Bash):**
```bash
docker rm -f fintech-ml-serving 2>/dev/null || true
docker run -d \
  --name fintech-ml-serving \
  --network fintech_default \
  -p 8000:8000 \
  --env-file .env \
  -e MLFLOW_TRACKING_URI=http://mlflow:5000 \
  -e MLFLOW_S3_ENDPOINT_URL=http://minio:9000 \
  -e MODEL_NAME=fraud-detector \
  -e MODEL_ALIAS=production \
  -v "$(pwd)/ml/visualization/data:/app/ml/visualization/data:ro" \
  fintech-ml-serving:latest
```

Check the container logs to confirm the `@production` model loaded cleanly:
```bash
docker logs fintech-ml-serving
```
You should see structured JSON logs ending with:
`"message": "Successfully loaded model 'fraud-detector' v1 (@production) in ...s"` and `"Application startup complete."`

---

### Phase 5 — Verify All Endpoints & Golden Parity Cases

Run these commands to verify that every endpoint of the serving service is healthy and accurate:

#### 1. Health & Model Info Checks
```bash
curl http://localhost:8000/health/live
curl http://localhost:8000/health/ready
curl http://localhost:8000/model-info
```

#### 2. Test `/predict` with a Real Fraud Transaction
**Windows (PowerShell):**
```powershell
Invoke-RestMethod -Uri "http://localhost:8000/predict" -Method Post -ContentType "application/json" -Body '{"transaction_id":"tx-test-001","step":6,"type":"CASH_OUT","amount":17025.02,"oldbalanceOrg":17025.02,"newbalanceOrig":0.0,"oldbalanceDest":0.0,"newbalanceDest":17025.02}' | ConvertTo-Json -Depth 5
```

**Linux / macOS (Bash):**
```bash
curl -s -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{
    "transaction_id": "tx-test-001",
    "step": 6,
    "type": "CASH_OUT",
    "amount": 17025.02,
    "oldbalanceOrg": 17025.02,
    "newbalanceOrig": 0.0,
    "oldbalanceDest": 0.0,
    "newbalanceDest": 17025.02
  }'
```

#### 3. Verify All 6 Golden Parity Cases Automatically
Run this one-liner to test `/predict` against all 6 Golden Parity Cases in [`ml/training/package/parity_cases.json`](ml/training/package/parity_cases.json):

```bash
python -c "import json, urllib.request; cases = json.load(open('ml/training/package/parity_cases.json'))['cases']; [print(c['case_id'], '-> PASS') for c in cases if (lambda r: abs(r['fraud_probability'] - c['expected_output']['fraud_probability']) <= 1e-5 and r['is_fraud_predicted'] == c['expected_output']['is_fraud_predicted'])(json.loads(urllib.request.urlopen(urllib.request.Request('http://localhost:8000/predict', data=json.dumps({'transaction_id': c['case_id'], **c['raw_payload']}).encode(), headers={'Content-Type': 'application/json'})).read()))]"
```

#### 4. Verify 3D Projections (`/viz/*`) & Prometheus Metrics (`/metrics`)
```bash
curl -s http://localhost:8000/viz/pca | head -c 300
curl -s http://localhost:8000/metrics | grep ml_model_loaded
```

#### 5. Run Linter & Automated Unit Test Suites
```bash
ruff check ml/serving ml/pipeline
ruff format --check ml/serving ml/pipeline
pytest ml/pipeline/tests ml/serving/tests -v
```

---

## 5. Troubleshooting & Common Questions

| Symptom / Error | Root Cause | Solution |
| :--- | :--- | :--- |
| `Bind for 0.0.0.0:5432 failed: port is already allocated` | Local Windows PostgreSQL service is already running on host port `5432`. | Open `.env` and set `POSTGRES_PORT=5433`, then re-run `docker compose up -d`. |
| `! mlflow Warning pull access denied for fintech-mlflow` | Docker Compose checked Docker Hub before building the local image. | Harmless warning. Run `docker compose up -d --build` to build directly without checking Docker Hub. |
| `NoCredentialsError: Unable to locate credentials` when running `populate_mlflow` | `.env` file is missing at the project root. | Copy `.env.example` to `.env` (`cp .env.example .env`). `mlflow_config.py` automatically loads `.env`. |
| `InvalidAccessKeyId` or `SignatureDoesNotMatch` from MinIO | `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` in `.env` do not match `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD`, or volumes have old credentials. | Ensure both pairs match in `.env`. If you changed credentials after first boot, run `docker compose down -v && docker compose up -d`. |
| `GET /health/ready` returns `503 Service Unavailable` | Either `populate_mlflow` + `promote_model` haven't been run yet, or `fintech-ml-serving` started before `@production` existed. | Complete Phase 3 (`populate_mlflow` $\rightarrow$ `validate_gate` $\rightarrow$ `promote_model`), then restart serving: `docker restart fintech-ml-serving`. |
| `GET /viz/pca` returns `404 Not Found` | `fintech-ml-serving` was started without mounting `ml/visualization/data`. | Re-run the `docker run` command in Phase 4 including `-v "${PWD}/ml/visualization/data:/app/ml/visualization/data:ro"`. |
