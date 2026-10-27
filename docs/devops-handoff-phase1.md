# Phase 1 Handoff Pack — FastAPI ML Serving (Person 3 → Person 4 DevOps)

**Owner:** Role 5 / Person 3 (MLOps & ML Serving Engineer)  
**Recipient:** Role 3 / Person 4 (DevOps & Cloud Infrastructure Engineer)  
**Dockerfile Path:** [`ml/serving/Dockerfile`](../ml/serving/Dockerfile) (Build context: **repository root `.`**)

---

## 1. Container Build & Run Contract

> **Important:** The Docker build context **must be the repository root (`.`)** so that `ml/serving/Dockerfile` can copy both `ml/common/` (shared PaySim preprocessing) and `ml/serving/`.

```bash
# Build from repository root
docker build -f ml/serving/Dockerfile -t ghcr.io/oubay-s/fintech-ml-serving:latest .

# Run locally
docker run --rm -p 8000:8000 --env-file .env.example ghcr.io/oubay-s/fintech-ml-serving:latest
```

---

## 2. Kubernetes Probes, Security & Resource Specifications

| Property | Canonical Value | Notes |
| :--- | :--- | :--- |
| **Container Port** | `8000` | HTTP REST |
| **Process UID / User** | `1001` (`mluser`) | Non-root execution (`runAsNonRoot: true`, `runAsUser: 1001`) |
| **Liveness Probe** | `GET /health/live` | Returns `200 OK` immediately on process start (`initialDelaySeconds: 5`, `periodSeconds: 10`) |
| **Readiness Probe** | `GET /health/ready` | Returns `503` until MLflow model + `uncertainty_config.json` are loaded; `200 OK` when ready (`initialDelaySeconds: 5`, `periodSeconds: 10`) |
| **Prometheus Scrape** | `GET /metrics` (port `8000`) | Exempt from `X-Internal-Api-Key` |
| **CPU Request / Limit** | `250m` / `1000m` | Single Uvicorn worker per pod; scale horizontally via HPA |
| **Memory Request / Limit** | `384Mi` / `768Mi` | Typical resident memory ~180–240 MB with sklearn/xgboost loaded |
| **Model Rollout Policy** | Rolling restart (`kubectl rollout restart`) | No runtime hot-swap; pods load `@production` alias on startup |

---

## 3. Environment Variables & Secrets Contract (`ConfigMap` / `Secret`)

| Variable | Kind | Default / Example | Description |
| :--- | :--- | :--- | :--- |
| `PORT` | ConfigMap | `8000` | HTTP listen port |
| `LOG_LEVEL` | ConfigMap | `INFO` | Structured JSON log level |
| `MLFLOW_TRACKING_URI` | ConfigMap | `http://fintech-mlflow:5000` | MLflow Tracking & Registry server URL |
| `MODEL_NAME` | ConfigMap | `fraud-detector` | Registered model name in MLflow |
| `MODEL_ALIAS` | ConfigMap | `production` | MLflow 2.x model alias (`@production`) |
| `MLFLOW_S3_ENDPOINT_URL` | ConfigMap | `http://fintech-minio:9000` | MinIO S3 endpoint for artifact downloads |
| `VIZ_DATA_DIR` | ConfigMap | `/app/ml/visualization/data` | Path to precomputed PCA/t-SNE/UMAP JSON files |
| `VIZ_MAX_POINTS` | ConfigMap | `2000` | Max points returned per `/viz/{method}` call |
| `AWS_ACCESS_KEY_ID` | Secret | `minioadmin` | MinIO S3 access key |
| `AWS_SECRET_ACCESS_KEY` | Secret | `changeme_minio` | MinIO S3 secret key |
| `INTERNAL_API_KEY` | Secret | *(optional)* | Shared secret validated via `X-Internal-Api-Key` header |

---

## 4. Optional `docker-compose.yml` Service Snippet (For DevOps Integration)

*(Per team red-line rules, `docker-compose.yml` was not modified directly. Paste this block into `docker-compose.yml` when ready)*:

```yaml
  ml-serving:
    build:
      context: .
      dockerfile: ml/serving/Dockerfile
    container_name: fintech-ml-serving
    environment:
      PORT: "8000"
      MLFLOW_TRACKING_URI: http://mlflow:5000
      MLFLOW_S3_ENDPOINT_URL: http://minio:9000
      AWS_ACCESS_KEY_ID: ${MINIO_ROOT_USER:-minioadmin}
      AWS_SECRET_ACCESS_KEY: ${MINIO_ROOT_PASSWORD:-changeme_minio}
      MODEL_NAME: fraud-detector
      MODEL_ALIAS: production
      LOG_LEVEL: INFO
    ports:
      - "8000:8000"
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
