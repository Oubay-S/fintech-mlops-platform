# Engineering Conventions & Team Contracts

> **Status:** Proposal for Week 1 team alignment  
> **Audience:** Roles 1 to 5 (Backend, Frontend, DevOps/MLOps, ML Training, ML Serving)

---

## 1. Networking & Port Allocations

To prevent port collisions during local and integration runs, every service is assigned a strict, non-overlapping port:

| Component / Service | Default Port | Technology | Responsible Role |
|---------------------|--------------|------------|------------------|
| **API Gateway** | `8080` | Spring Cloud Gateway | Role 1 |
| **Auth Service** | `8081` | Spring Boot (JWT) | Role 1 |
| **Customer Service** | `8082` | Spring Boot | Role 1 |
| **Transaction Service** | `8083` | Spring Boot | Role 1 |
| **Risk Service** | `8084` | Spring Boot | Role 1 |
| **Notification Service** | `8085` | Spring Boot | Role 1 / Role 2 |
| **Audit Service** | `8086` | Spring Boot | Role 1 / Role 2 |
| **FastAPI ML Serving** | `8000` | Python / FastAPI / Uvicorn | Role 5 |
| **MLflow Tracking UI** | `5000` | MLflow Server | Role 3 |
| **PostgreSQL** | `5432` | Postgres 15+ | Role 3 (infra) |
| **MinIO API / Console** | `9000` / `9001` | MinIO S3 Server | Role 3 (infra) |
| **React Dashboard** | `3000` | React / Vite | Role 2 |
| **Prometheus** | `9090` | Prometheus Server | Role 3 (monitoring) |
| **Grafana** | `3001` | Grafana OSS | Role 3 (monitoring) |

---

## 2. Docker Images & Registry Naming Standard

All container images pushed to GitHub Container Registry (GHCR) must follow this pattern:

```
ghcr.io/oubay-s/fintech-<service-name>:<git-sha>
```

- **Image prefix:** `fintech-`
- **Tagging strategy:**
  - `:<short-sha>` for reproducible CI builds
  - `:latest` reserved strictly for default development runs
- **Examples:**
  - `ghcr.io/oubay-s/fintech-api-gateway:a1b2c3d`
  - `ghcr.io/oubay-s/fintech-risk-service:a1b2c3d`
  - `ghcr.io/oubay-s/fintech-ml-serving:a1b2c3d`

---

## 3. Git Workflow & Branching Conventions

- **Protected Branch:** `main` (no direct commits, 1 approval minimum).
- **Feature Branches:**
  ```
  feat/<role>-<topic>
  ```
  Examples:
  - `feat/role1-jwt-auth`
  - `feat/role2-react-dashboard-layout`
  - `feat/role3-k8s-base-manifests`
  - `feat/role4-model-benchmark`
  - `feat/role5-fastapi-stub`
- **Bugfix Branches:**
  ```
  fix/<role>-<topic>
  ```

---

## 4. Commit Message Standard (Conventional Commits)

Format: `<type>(<scope>): <summary>`

- `feat`: New feature
- `fix`: Bug fix
- `ci`: Pipelines and CI/CD changes
- `docs`: Documentation updates
- `refactor`: Code refactoring without behavior change
- `test`: Adding or adjusting tests
- `chore`: Tooling, dependencies, or repository maintenance

---

## 5. Configuration & Secret Management

- **12-Factor App Compliance:** All configurations must be injected strictly via environment variables.
- **Zero Hardcoded Secrets:** Docker images must never embed database credentials, tokens, or private keys.
- **Local Development:** Developers copy `.env.example` to `.env`. `.env` is ignored by Git.
- **Kubernetes:** Configurations live in `ConfigMaps`; credentials live in `Secrets` (managed locally or via CI/CD injection).

---

## 6. Health Checks & Observability Endpoints

Every service must provide health and Prometheus metric endpoints to allow Kubernetes probes and monitoring scrapers to operate:

### Spring Boot Microservices (Roles 1 & 2)
- **Health Check:** `GET /actuator/health`
- **Prometheus Metrics:** `GET /actuator/prometheus` (requires `micrometer-registry-prometheus` dependency)
- **Liveness & Readiness:** Handled natively by Spring Boot actuator probes under `/actuator/health/liveness` and `/actuator/health/readiness`.

### FastAPI Model Serving (Role 5)
- **Health Check:** `GET /health` (returns `{"status": "ok", "model_version": "..."}`)
- **Prometheus Metrics:** `GET /metrics` (instrumented using `prometheus-fastapi-instrumentator` or standard `prometheus_client`)

---

## 7. Service Image Quality Checklist

Before submitting a Dockerfile or container image to the repository, each developer must verify:
- [ ] **Single command start:** Image executes cleanly using `docker run -p <port>:<port> <image>`.
- [ ] **Documented port:** Exposed port aligns with the port allocation table above.
- [ ] **Working probes:** `/health` and `/metrics` respond with HTTP 200 within 5 seconds.
- [ ] **Environment-driven:** Modifying environment variables alters database URLs, credentials, and downstream endpoints without rebuilding the image.
- [ ] **Non-root execution:** Containers should run with a dedicated non-root user when possible.

---

## 8. Week 1 Open Decisions (To Be Finalized by the Team)

The following items are designated as **To Be Decided (TBD)** in Week 1 and require joint team consensus:

### A. Fraud Detection Dataset (Decision Owner: Role 4)
- **Candidate Options:**
  - Kaggle Credit Card Fraud Detection (284,807 transactions, 0.17% fraud rate, PCA-transformed features `V1-V28`, `Time`, `Amount`).
  - Synthetic Financial Datasets for Fraud Detection (PaySim: mobile money transactions with `type`, `amount`, `oldbalanceOrg`, etc.).
- **Decision Criteria:** Class imbalance realism, feature interpretability, latency implications for real-time serving.

### B. Uncertainty Threshold Ownership & Storage (Decision Owners: Roles 4 & 5)
- **Agreed Rule:** The uncertainty threshold (e.g., threshold above which a prediction is flagged for human review) is packaged directly within the model artifact package.
- **Access Rule:** Only Role 4 may adjust this threshold during validation; Role 5 reads it dynamically from the MLflow artifact during startup.

### C. OpenAPI Specification Contract for `/predict` (Decision Owner: Role 5 -> Consumed by Role 1)
- Endpoint: `POST /predict`
- **Agreed Contract Fields:**
  ```json
  {
    "request": {
      "transaction_id": "string",
      "customer_id": "string",
      "amount": 1500.0,
      "features": { ... }
    },
    "response": {
      "prediction": "FRAUD | LEGITIMATE",
      "probability": 0.84,
      "uncertainty": 0.22,
      "model_version": "v1.0.0",
      "action": "BLOCK | ALLOW | HUMAN_REVIEW"
    }
  }
  ```
- **Deadline:** Role 5 to deliver the formal `openapi.yaml` stub by end of Week 1 so Role 1 can mock the HTTP client in `risk-service`.
