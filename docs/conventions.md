# Engineering Conventions & Team Contracts (Plan V2.2 Aligned)

> **Status:** Reference Document — Aligned with `APPLICATION_CONCEPTION_PLAN V2.2` (28 October 2026)  
> **Audience:** Roles 1 to 5 (Backend Lead, Frontend & Delivery, DevOps & MLOps, ML Training, ML Serving)

---

## 1. Networking & Port Allocations

To prevent port collisions during local and integration runs, every service is assigned a strict, non-overlapping port:

| Component / Service | Default Port | Technology | Responsible Role |
|---------------------|--------------|------------|------------------|
| **API Gateway** | `8080` | Spring Cloud Gateway | Role 1 |
| **Auth Service** | `8081` | Spring Boot (JWT RS256 / JWKS) | Role 1 |
| **Customer Service** | `8082` | Spring Boot | Role 1 |
| **Transaction Service** | `8083` | Spring Boot | Role 1 |
| **Risk Service** | `8084` | Spring Boot | Role 1 |
| **Notification Service** | `8085` | Spring Boot | Role 1 / Role 2 |
| **Audit Service** | `8086` | Spring Boot | Role 1 / Role 2 |
| **FastAPI ML Serving** | `8000` | Python 3.11 / FastAPI / Uvicorn | Role 5 |
| **MLflow Tracking UI** | `5000` | MLflow Server (PostgreSQL + S3) | Role 3 |
| **PostgreSQL 15+** | `5432` | PostgreSQL (6 isolated schemas) | Role 3 (infra) |
| **MinIO S3 API / Console** | `9000` / `9001` | Silo / MinIO S3 Object Store | Role 3 (infra) |
| **RabbitMQ AMQP / UI** | `5672` / `15672`| RabbitMQ 3 Management | Role 3 (infra) |
| **Mailpit SMTP / UI** | `1025` / `8025` | Mailpit Email Catcher | Role 3 (infra) |
| **React Dashboard** | `3000` | React 18 / Vite / MUI | Role 2 |
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
- **Base image standards:**
  - Spring Boot: Eclipse Temurin JRE 21 Alpine (multi-stage build, non-root user `1001`, JVM `-XX:MaxRAMPercentage=75 -XX:+UseG1GC`)
  - FastAPI: Python 3.11-slim (non-root user `1001`)
  - React Dashboard: Nginx Alpine (unprivileged)

---

## 3. Financial Scale, Balances & Invariants (PaySim Aligned)

In accordance with Section 11.2 of the Conception Plan V2.2, all money amounts operate at **PaySim magnitudes**:

- **Currency:** Simulated PaySim currency units.
- **Initial Balances (`app.wallet.initial-balance`):**
  - **Regular Customers:** `1,000,000.00` credited upon registration via `TOPUP` ledger entry.
  - **Cash Agents (`accountKind = AGENT`):** `0.00` initial balance.
- **Transfer Limits (`app.transfer.max-amount`):** `10,000,000.00`.
- **High-Amount Threshold (`risk.policy.high-amount-threshold`):** `500,000.00` (provisional R5 threshold).
- **Core Operations:**
  - `TRANSFER`: Customer to customer.
  - `CASH_OUT`: Customer to Cash Agent (`accountKind = AGENT`). Both are **core MUST** operations.
- **Financial Invariants (Zero Money Creation/Loss):**
  - **I1:** `wallet.balance` = $\sum(\text{TOPUP} + \text{CREDIT} - \text{DEBIT})$
  - **I2:** `wallet.held_amount` = $\sum(\text{HOLD} - \text{RELEASE})$
  - **I3:** Total system balances equal total admin top-ups: $\sum \text{balances} = \sum \text{TOPUPs}$.
  - Verification endpoint: `GET /admin/ledger/verify` (called after chaos tests and integration runs).

---

## 4. Frozen ML Inference Contract (`POST /predict`)

The ML inference contract between `risk-service` and `ml-serving` is **100% frozen** (Section 17 & 24.2):

### Request (`POST /predict`):
Risk Service sends **strictly these 6 PaySim fields**:
```json
{
  "transaction_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "type": "TRANSFER",
  "amount": 1000.00,
  "sender_old_balance": 5000.00,
  "sender_new_balance": 4000.00,
  "receiver_old_balance": 200.00,
  "receiver_new_balance": 1200.00
}
```
*Note:* All derived features (drain ratio, zero balance after, amount equals old balance) are computed **internally by ML Serving**. Risk never sends more than these 6 fields.

### Response (`POST /predict`):
```json
{
  "transaction_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "prediction": "LEGITIMATE",
  "fraud_probability": 0.04,
  "prediction_set": ["legit"],
  "uncertainty": {
    "is_uncertain": false,
    "score": 0.08
  },
  "action": "ALLOW",
  "model_version": "fraud-detector-v1.0",
  "explanations": [
    {"feature": "amount", "attribution": 0.35, "description": "Normal transfer amount"},
    {"feature": "sender_old_balance", "attribution": 0.20, "description": "Sufficient balance"}
  ]
}
```
- **Performance Budget:** p95 latency **< 300 ms** at target load.
- **Explanations:** Must be computed cheaply (top 3 features from native model attributions). Model-agnostic SHAP per request is strictly forbidden as it violates the 300 ms latency budget.
- **Model Types:** ML model is trained on all 5 PaySim types, but production application traffic only generates `TRANSFER` and `CASH_OUT`.

---

## 5. Risk Decision Policy (Rules R1 – R6)

The Risk Service owns the final binding decision; ML `action` is a suggestion only:

| Rule | Condition | Decision | Reason Tag |
|---|---|---|---|
| **R1** | Sender wallet equals receiver wallet | `REJECTED` | `SELF_TRANSFER` |
| **R1b**| Transaction type is not `TRANSFER` or `CASH_OUT` | `REJECTED` | `INVALID_TRANSACTION_TYPE` |
| **R2** | ML service degraded, timeout (> 800 ms), or circuit breaker open | `PENDING_REVIEW` | `SERVICE_DEGRADED` |
| **R3** | Model prediction set is `{fraud}` | `REJECTED` | `MODEL_FRAUD` |
| **R4** | Model prediction set is uncertain (`{legit, fraud}` or `{}`) | `PENDING_REVIEW` | `MODEL_UNCERTAIN` |
| **R5** | Model `{legit}` BUT `amount >= 500,000.00` (high amount) | `PENDING_REVIEW` | `AMOUNT_HIGH` |
| **R6** | Model `{legit}` AND `amount < 500,000.00` | `APPROVED` | `AUTO_APPROVED` |

---

## 6. Observability, Metrics & Alerts

All services must expose standard Prometheus metrics. Custom business metrics are a binding contract with Grafana dashboards:

### Key Metrics:
- `fintech_decisions_total`: Counter with tags `decision`, `reason`, `degraded`, `scored`.
- `fintech_ml_call_seconds`: Histogram of ML call latencies (`outcome`).
- `fintech_review_cases_open`: Gauge tagged by `priority`.
- `fintech_wallet_lock_wait_seconds`: Timer measuring optimistic/pessimistic lock contention.

### Derived PromQL Signals (DevOps Alerting):
- **Uncertainty Ratio (ML Uncertainty High Alert):** Calculated strictly on `reason="MODEL_UNCERTAIN"` over all scored decisions (excluding `AMOUNT_HIGH` and `SERVICE_DEGRADED`):
  ```promql
  sum(rate(fintech_decisions_total{reason="MODEL_UNCERTAIN"}[5m]))
  /
  sum(rate(fintech_decisions_total{scored="true"}[5m])) > 0.25
  ```
- **Degraded Ratio:** Ratio of `reason="SERVICE_DEGRADED"` over total decisions.

---

## 7. Health Checks & Kubernetes Probes

Every service must provide health endpoints adhering to Kubernetes lifecycle requirements:

### Spring Boot Services (Roles 1 & 2):
- **Startup Probe:** `/actuator/health/liveness` with `failureThreshold: 30`, `periodSeconds: 2` (tolerates 30–60s cold start).
- **Liveness Probe:** `/actuator/health/liveness` (`periodSeconds: 10`).
- **Readiness Probe:** `/actuator/health/readiness` (must check DB connectivity ONLY, never downstream microservices).
- **Metrics:** `GET /actuator/prometheus`.

### FastAPI Model Serving (Role 5):
- **Liveness:** `GET /health/live` (process is responsive).
- **Readiness:** `GET /health/ready` (returns `200 OK` **strictly after the model is loaded into memory**).
- **Metadata & Viz:** `GET /model-info` and `GET /viz/{pca|tsne|umap}`.
- **Metrics:** `GET /metrics`.

---

## 8. Deterministic Triggers for Demos and E2E Tests

To ensure automated Playwright E2E tests and live demonstrations are 100% reproducible:
- **`APPROVED` trigger:** A partial transfer with amount `< 500,000.00` to a known receiver.
- **`REJECTED` trigger:** A transfer of the **entire balance** to a new receiver (*drain pattern*).
- **`PENDING_REVIEW` trigger:**
  - *Rule-driven:* A transfer with amount $\ge 500,000.00$ (`AMOUNT_HIGH`).
  - *Resilience-driven:* Any transfer executed while the ML service/stub is stopped (`SERVICE_DEGRADED`).

---

## 9. Git & Pull Request Workflow

- **Branch Protection on `main`:** Direct push disabled, 1 peer review required, `CI Quality Gate Status` check required and passing.
- **Branch Naming Standard:** `feat/<role>-<topic>` (e.g., `feat/role1-auth-jwt`, `feat/role4-paysim-eda`).
- **Conventional Commits:** `feat`, `fix`, `ci`, `docs`, `test`, `refactor`, `chore`.
- **Automated Issue Closure:** Include `Closes #<issue_id>` in the PR description.
