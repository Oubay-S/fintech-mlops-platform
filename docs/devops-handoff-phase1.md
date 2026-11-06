# DevOps Handoff Pack — FastAPI ML Serving & MLOps Pipeline (Role 5 → Role 3 DevOps)

**Owner:** Role 5 / Person 3 (MLOps & ML Serving Engineer)  
**Recipient:** Role 3 / Person 4 (DevOps & Cloud Infrastructure Engineer)  
**Dockerfile Path:** [`ml/serving/Dockerfile`](ml/serving/Dockerfile) (Build context: **repository root `.`**)  
**Status:** Verified End-to-End (Phases 1–5 Complete)

---

## 1. Container Build & Run Contract

> **Important:** The Docker build context **must be the repository root (`.`)** so that `ml/serving/Dockerfile` can copy `ml/common/`, `ml/serving/`, and `docs/api/ml-predict-openapi.yaml`.

```bash
# Build production image from repository root
docker build -f ml/serving/Dockerfile -t fintech-ml-serving:latest .

# Run connected to the Docker Compose platform network (fintech_default)
# Credentials and host port overrides are loaded securely via --env-file .env
docker run -d --name fintech-ml-serving \
  --network fintech_default \
  -p 8000:8000 \
  --env-file .env \
  -v "${PWD}/ml/visualization/data:/app/ml/visualization/data:ro" \
  -e MLFLOW_TRACKING_URI=http://mlflow:5000 \
  -e MLFLOW_S3_ENDPOINT_URL=http://minio:9000 \
  -e MODEL_NAME=fraud-detector \
  -e MODEL_ALIAS=production \
  fintech-ml-serving:latest
```

---

## 2. Kubernetes Probes, Security & Resource Specifications

| Property | Canonical Value | Notes |
| :--- | :--- | :--- |
| **Container Port** | `8000` | HTTP REST |
| **Process UID / User** | `1001` (`mluser`) | Non-root execution (`runAsNonRoot: true`, `runAsUser: 1001`) |
| **Liveness Probe** | `GET /health/live` | Returns `200 OK` immediately on process start (`initialDelaySeconds: 5`, `periodSeconds: 10`) |
| **Readiness Probe** | `GET /health/ready` | Returns `503` until MLflow model + `uncertainty_config.json` are loaded and SHA-256 verified; `200 OK` when ready (`initialDelaySeconds: 5`, `periodSeconds: 10`) |
| **Prometheus Scrape** | `GET /metrics` (port `8000`) | Exposes 134 `ml_*` series; exempt from `X-Internal-Api-Key` |
| **CPU Request / Limit** | `250m` / `1000m` | Single Uvicorn worker per pod; scale horizontally via HPA (`minReplicas: 2`, `maxReplicas: 6`, target CPU `70%`) |
| **Memory Request / Limit** | `384Mi` / `768Mi` | Typical resident memory ~190–240 MB with `scikit-learn==1.6.1` + `xgboost==2.1.4` loaded |
| **Model Rollout Policy** | Rolling restart (`kubectl rollout restart deployment/fintech-ml-serving`) | Zero-downtime rollout; new pods load `@production` alias before passing `/health/ready` |

---

## 3. Environment Variables & Secrets Contract (`ConfigMap` / `Secret`)

| Variable | Kind | Default / Example | Description |
| :--- | :--- | :--- | :--- |
| `PORT` | ConfigMap | `8000` | HTTP listen port |
| `LOG_LEVEL` | ConfigMap | `INFO` | Structured JSON log level |
| `MLFLOW_TRACKING_URI` | ConfigMap | `http://mlflow:5000` | MLflow Tracking & Registry server URL |
| `MODEL_NAME` | ConfigMap | `fraud-detector` | Registered model name in MLflow |
| `MODEL_ALIAS` | ConfigMap | `production` | MLflow 2.x model alias (`@production`) |
| `MLFLOW_S3_ENDPOINT_URL` | ConfigMap | `http://minio:9000` | MinIO S3 endpoint for artifact downloads |
| `VIZ_DATA_DIR` | ConfigMap | `/app/ml/visualization/data` | Path to precomputed PCA/t-SNE/UMAP JSON files (`pca.json`, `tsne.json`, `umap.json`) |
| `VIZ_MAX_POINTS` | ConfigMap | `2000` | Max points returned per `/viz/{method}` call |
| `AWS_ACCESS_KEY_ID` | Secret | Loaded from `.env` or K8s Secret | MinIO S3 access key |
| `AWS_SECRET_ACCESS_KEY` | Secret | Loaded from `.env` or K8s Secret | MinIO S3 secret key |
| `INTERNAL_API_KEY` | Secret | *(optional)* | Shared secret validated in constant time via `X-Internal-Api-Key` header |

---

## 4. Automated MLOps Pipeline Commands (For CI/CD & K8s Init/Seeder Job)

When a new MLflow + PostgreSQL + MinIO stack starts (in CI or in a fresh Kubernetes cluster), the database is initially empty. Run the following 4 deterministic commands in order to seed the benchmark runs, validate the Quality Gate, and promote the Champion model to `@production`:

```bash
# 1. Seed benchmark runs (lr, rf, svm, mlp) and register Champion XGBoost as @candidate
python -m ml.pipeline.populate_mlflow --tracking-uri http://mlflow:5000

# 2. Run automated MLOps Quality Gate (read-only audit; exits 0 on pass, 1 on gate failure, 2 on infra error)
python -m ml.pipeline.validate_gate --alias candidate --tracking-uri http://mlflow:5000

# 3. Promote @candidate -> @staging
python -m ml.pipeline.promote_model --from-alias candidate --to-alias staging --tracking-uri http://mlflow:5000

# 4. Promote @staging -> @production (atomically rotates any existing @production version to @previous)
python -m ml.pipeline.promote_model --from-alias staging --to-alias production --tracking-uri http://mlflow:5000
```

### Instant Rollback Command (Incident Response)
```bash
python -m ml.pipeline.promote_model --from-alias previous --to-alias production --tracking-uri http://mlflow:5000
kubectl rollout restart deployment/fintech-ml-serving
```

---

## 5. `docker-compose.yml` Service Snippet (For DevOps Integration)

*(Per team ownership boundaries, `docker-compose.yml` is owned by Role 3 DevOps. Add this service block to `docker-compose.yml`)*:

```yaml
  ml-serving:
    build:
      context: .
      dockerfile: ml/serving/Dockerfile
    image: fintech-ml-serving:latest
    container_name: fintech-ml-serving
    environment:
      PORT: "8000"
      MLFLOW_TRACKING_URI: http://mlflow:5000
      MLFLOW_S3_ENDPOINT_URL: http://minio:9000
      AWS_ACCESS_KEY_ID: ${AWS_ACCESS_KEY_ID:-${MINIO_ROOT_USER}}
      AWS_SECRET_ACCESS_KEY: ${AWS_SECRET_ACCESS_KEY:-${MINIO_ROOT_PASSWORD}}
      MODEL_NAME: fraud-detector
      MODEL_ALIAS: production
      VIZ_DATA_DIR: /app/ml/visualization/data
      LOG_LEVEL: INFO
    volumes:
      - ./ml/visualization/data:/app/ml/visualization/data:ro
    ports:
      - "${FASTAPI_PORT:-8000}:8000"
    depends_on:
      mlflow:
        condition: service_healthy
    deploy:
      resources:
        limits:
          memory: 512M
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=3)"]
      interval: 15s
      timeout: 5s
      retries: 5
    restart: unless-stopped
```
