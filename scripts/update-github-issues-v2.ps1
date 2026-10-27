# PowerShell script to update all 34 GitHub Issues with detailed V2.1 specifications
$repo = "Oubay-S/fintech-mlops-platform"
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")

$issueUpdates = @{
    # --------------------------------------------------------------------------
    # ROLE 1 : BACKEND (Spring Boot)
    # --------------------------------------------------------------------------
    1 = @"
## Overview & Architecture Specification
Implement the **API Gateway** as the single public entry point for all frontend client traffic.
- **Technology:** Spring Cloud Gateway (Java 21, Spring Boot 3.5.x)
- **Port:** `8080` (publicly exposed through Ingress)
- **Reference:** APPLICATION_CONCEPTION_PLAN V2.1 Sections 10.3, 10.4, 16.7

## Key Responsibilities
1. **Route Mapping:**
   - `/auth/**`, `/admin/users/**` -> Auth Service (`:8081`)
   - `/customers/**` -> Customer Service (`:8082`)
   - `/wallet/**`, `/transfers/**`, `/payment-requests/**`, `/admin/wallets/**`, `/admin/ledger/**` -> Transaction Service (`:8083`)
   - `/risk/**` -> Risk Service (`:8084`)
   - `/notifications/**` -> Notification Service (`:8085`)
   - `/audit/**` -> Audit Service (`:8086`)
2. **Security & Perimeter Defense:**
   - **STRICTLY BLOCK** `/internal/**` routes from external access (returns `403 Forbidden`).
   - Strip client-supplied identity headers (`X-User-Id`, `X-User-Roles`).
   - Inject `X-Correlation-Id` (UUID) into every downstream request and return it in HTTP response headers.
   - Validate JWT signatures for protected routes.
3. **Rate Limiting (Bucket4j per replica):**
   - `POST /auth/login`: 5 req / min per IP (exceeding returns `429`)
   - `POST /auth/register`: 3 req / hour per IP
   - `POST /customers/lookup`: 10 req / min per user
   - `POST /payment-requests`: 5 req / min per user
   - All other endpoints: 200 req / min per user
4. **Timeouts:** Connect timeout 1s, response timeout 5s.

## Definition of Done (DoD)
- [ ] Gateway routes traffic correctly to all 6 backend services.
- [ ] `/internal/**` cannot be reached from outside.
- [ ] Rate limits trigger HTTP 429 when thresholds are exceeded.
- [ ] Every response includes `X-Correlation-Id`.
"@

    2 = @"
## Overview & Architecture Specification
Implement the **Auth Service** handling credentials, tokens, lockout, and user provisioning events.
- **Port:** `8081` | **Database Schema:** `auth` (PostgreSQL 16)
- **Reference:** APPLICATION_CONCEPTION_PLAN V2.1 Sections 10.1, 10.2, 13.2, 16.1

## Key Responsibilities & Endpoints
1. **Registration (`POST /auth/register`):**
   - Validate email, username, phone uniqueness. Password minimum 10 chars, hashed with BCrypt.
   - Insert user with `role = CUSTOMER`.
   - **Transactional Outbox:** Write `UserRegistered` event in the *same* database transaction to trigger profile and wallet provisioning.
2. **Authentication (`POST /auth/login`):**
   - Count failed attempts in last 15 min from `login_attempts` table. If >= 5 -> return `429 ACCOUNT_LOCKED`.
   - Generic `401 INVALID_CREDENTIALS` for wrong password or unknown user.
   - Return RS256 JWT access token (15 min TTL) in body and set opaque rotating refresh token (7 days TTL) in `httpOnly`, `SameSite=Strict` cookie.
3. **Token Refresh (`POST /auth/refresh`) & Logout (`POST /auth/logout`):**
   - Automatic token rotation: issuing new access token generates a new refresh token and revokes the previous one.
   - **Reuse detection:** If an already-rotated token is submitted, immediately revoke the entire token chain.
4. **JWKS & Service Identity:**
   - `GET /.well-known/jwks.json`: Public keys for inter-service RS256 signature verification.
   - `POST /internal/auth/service-token`: Client credentials flow for machine-to-machine `SERVICE` tokens.
5. **Staff Creation (`POST /admin/users`):** Admin creates `ANALYST`, `ADMIN`, or cash `AGENT` accounts.

## Definition of Done (DoD)
- [ ] Registration emits `UserRegistered` event to outbox.
- [ ] Login returns RS256 JWT + httpOnly cookie.
- [ ] Account locks out after 5 consecutive failed attempts.
- [ ] Refresh token rotation and reuse detection verified by automated tests.
"@

    3 = @"
## Overview & Architecture Specification
Implement the core financial services: **Customer Service** (identities & lookup) and **Transaction Service** (wallets, double-entry ledger, transfers, payment requests).
- **Customer Service:** Port `8082`, Schema `customer`
- **Transaction Service:** Port `8083`, Schema `transaction`
- **Reference:** APPLICATION_CONCEPTION_PLAN V2.1 Sections 11.1-11.5, 13.2, 16.2, 16.3

## Key Responsibilities & Rules
1. **Receiver Lookup (`POST /customers/lookup`):**
   - Rate limited (10/min/user). Resolves identifier to `{ receiverId, maskedName }` for payment confirmation. Never returns cash agents.
2. **Append-Only Ledger & Invariants (Transaction Service):**
   - Table `ledger_entries` records `TOPUP`, `HOLD`, `RELEASE`, `DEBIT`, `CREDIT`. Never updated or deleted.
   - **Invariant I1:** `balance` = sum(TOPUP + CREDIT - DEBIT).
   - **Invariant I2:** `held_amount` = sum(HOLD - RELEASE).
   - **Invariant I3:** sum(all balances) = sum(all TOPUP entries). Money is conserved!
   - Concurrency: `SELECT ... FOR UPDATE` on wallets **locked in ascending wallet-ID order** to prevent deadlocks.
3. **Transfer Lifecycle & Idempotency (`POST /transfers`):**
   - Requires `Idempotency-Key` header (UUID). Stores response in `idempotency_keys` table (24h retention).
   - **Tx1:** Validate balance, lock wallets, write `HOLD`, insert transfer `PROCESSING`, commit.
   - Synchronous call to Risk Service (`POST /internal/decisions`).
   - **Tx2:** Apply decision: `APPROVED` -> RELEASE + DEBIT + CREDIT; `REJECTED` -> RELEASE hold; `PENDING_REVIEW` -> keep hold.
4. **Live Payment Requests (`POST /payment-requests`):**
   - 2-minute TTL (`expiresAt = created_at + 2min`). Server-side enforced.
   - Payer incoming query polled every 5s. Scoring and funds check happen *only upon acceptance*.
5. **Stuck-Transfer Reconciler:** Background job every 30s checks transfers `PROCESSING` > 2 min and reconciles with Risk.
6. **Invariants Verification (`GET /admin/ledger/verify`):** Recomputes I1-I3 and reports violations (run after every chaos test).

## Definition of Done (DoD)
- [ ] 50 concurrent transfers across 3 wallets assert zero deadlocks, balances >= 0, and invariants I1-I3 intact.
- [ ] Idempotent retries return identical responses without double debit.
- [ ] Payment request expires after exactly 2 minutes.
"@

    4 = @"
## Overview & Architecture Specification
Create optimized multi-stage Dockerfiles for all Spring Boot services following modern DevOps best practices.
- **Reference:** APPLICATION_CONCEPTION_PLAN V2.1 Section 24.1 & `docs/dockerfiles-templates.md`

## Key Requirements
1. **Multi-Stage Build:**
   - Stage 1: `maven:3.9-eclipse-temurin-21-alpine` for building application JAR with dependency caching (`mvn dependency:go-offline`).
   - Stage 2: `eclipse-temurin:21-jre-alpine` runtime image.
2. **Container Security:**
   - Run as non-root user `appuser` (UID `1001`, GID `1001`).
3. **JVM Memory Tuning:**
   - Set `ENV JAVA_OPTS="-XX:MaxRAMPercentage=75 -XX:+UseG1GC"` to prevent container OOMKills in Kubernetes.
4. **Services to Containerize:**
   - `services/api-gateway`
   - `services/auth-service`
   - `services/customer-service`
   - `services/transaction-service`
   - `services/risk-service`
   - `services/notification-service`
   - `services/audit-service`

## Definition of Done (DoD)
- [ ] All Dockerfiles build cleanly with Docker BuildKit.
- [ ] Final images run as UID 1001 and start in a single command.
- [ ] `.dockerignore` files present in each service directory.
"@

    5 = @"
## Overview & Architecture Specification
Implement the **Risk Service** evaluating incoming financial transactions through decision policy rules R1-R6 and orchestrating the human review queue.
- **Port:** `8084` | **Database Schema:** `risk`
- **Reference:** APPLICATION_CONCEPTION_PLAN V2.1 Sections 11.6, 11.7, 11.8, 16.4, 17

## Key Responsibilities & Decision Policy
1. **Decision Endpoint (`POST /internal/decisions`):**
   - Idempotent per `transfer_id`. Evaluates transaction rules in strict sequence:
   - **R1:** Sender or receiver not `ACTIVE` -> `REJECTED` (`ACCOUNT_RESTRICTED`)
   - **R1b:** Unsupported type & high amount -> `PENDING_REVIEW` / otherwise `APPROVED`
   - **R2:** ML service down, timeout, or circuit open -> `PENDING_REVIEW` with `degraded=true`
   - **R3:** Prediction set = `{fraud}` -> `REJECTED` (`MODEL_HIGH_RISK`)
   - **R4:** Prediction set = `{legit, fraud}` or empty -> `PENDING_REVIEW` (`MODEL_UNCERTAIN`)
   - **R5:** Prediction set = `{legit}` and amount >= high threshold -> `PENDING_REVIEW` (`AMOUNT_HIGH`)
   - **R6:** Prediction set = `{legit}` -> `APPROVED`
2. **Resilience4j Configuration (Risk -> ML Serving):**
   - Connect timeout 500ms, Read timeout 1500ms, 1 retry on 5xx.
   - Circuit Breaker: window 20 calls, opens at 50% failures, fallback to Rule R2.
3. **Review Queue & Case Management:**
   - `GET /risk/cases` (filters by status, deadline, priority).
   - `GET /risk/cases/{id}`: Snapshot of sender/receiver profile + ML prediction + explanations. **Audited!**
   - `POST /risk/cases/{id}/decision`: Analyst submits `APPROVE` or `REJECT` with mandatory reason (>= 10 chars).
   - Background job expires unclaimed cases after 24h (`REJECT_EXPIRED`).
   - Delivers outcome to Transaction Service via Outbox (`POST /internal/transfers/{id}/review-outcome`).

## Definition of Done (DoD)
- [ ] Table-driven JUnit tests validating rules R1 to R6.
- [ ] Circuit breaker opens on ML downtime and falls back to R2 (`degraded=true`).
- [ ] Review outcome reliably delivered to Transaction Service.
"@

    6 = @"
## Overview & Architecture Specification
Implement the **Notification Service** and **Audit Service** for asynchronous event logging and user communications.
- **Notification Service:** Port `8085`, Schema `notification`
- **Audit Service:** Port `8086`, Schema `audit`
- **Reference:** APPLICATION_CONCEPTION_PLAN V2.1 Sections 13.2, 15.2, 16.5, 16.6

## Key Responsibilities
1. **Notification Service:**
   - In-app notifications: `GET /notifications`, unread count badge `GET /notifications/unread-count`, mark read.
   - Email notifications: Dispatches HTML/text emails via Mailpit SMTP (`localhost:1025`). Email failures are logged and never block transactions.
   - Event consumer: Deduplicates received events by `eventId`.
2. **Audit Service:**
   - **Append-only ledger:** Database user has `INSERT` and `SELECT` privileges only (no UPDATE, no DELETE).
   - `GET /audit` (ADMIN only) with filters: actor, action, resource, date range.
   - Logs all critical events: `USER_REGISTERED`, `LOGIN_SUCCESS`, `TRANSFER_COMPLETED`, `TRANSFER_REJECTED`, `DECISION_MADE`, `CASE_VIEWED`, `CASE_DECIDED`, `WALLET_TOPUP`.
   - Never on the critical path: if Audit is down, transfers continue and events queue up in producer outbox tables.

## Definition of Done (DoD)
- [ ] Mailpit receives email notifications upon transfer completion.
- [ ] In-app unread notification count updates in real time.
- [ ] Audit service records all required actions with tamper-proof integrity.
"@

    7 = @"
## Overview & Architecture Specification
Instrument all Spring Boot services with Actuator, Prometheus metrics, and Kubernetes probes.
- **Reference:** APPLICATION_CONCEPTION_PLAN V2.1 Sections 22.1, 22.2, 24.1

## Key Responsibilities
1. **Add Dependencies:** Include `spring-boot-starter-actuator` and `micrometer-registry-prometheus` in `platform-starter`.
2. **Kubernetes Health Probes:**
   - `/actuator/health/liveness`: Process is alive (JVM state).
   - `/actuator/health/readiness`: **Own database connection ONLY**. Never check downstream microservices (prevents cascading outage).
   - Configure `server.shutdown=graceful` with 30s timeout.
3. **Custom Application Metrics:**
   - `fintech_transfers_total{status, reason}`
   - `fintech_payment_requests_total{status}`
   - `fintech_wallet_lock_wait_seconds`
   - `fintech_decisions_total{decision, degraded, scored}`
   - `fintech_ml_call_seconds`
   - `fintech_review_cases_open{priority}`
   - `fintech_outbox_pending{service}`
4. **Structured Logging:** Output JSON logs to stdout including `timestamp`, `level`, `service`, `correlationId`, `userId` (hashed).

## Definition of Done (DoD)
- [ ] All services expose `/actuator/health` and `/actuator/prometheus`.
- [ ] Custom business metrics increment correctly during transfers.
- [ ] Liveness and readiness probes respond within 200ms.
"@

    # --------------------------------------------------------------------------
    # ROLE 2 : FRONTEND & DELIVERY (React + Vite)
    # --------------------------------------------------------------------------
    8 = @"
## Overview & Architecture Specification
Initialize the Single Page Application (SPA) dashboard for customers, fraud analysts, and administrators.
- **Stack:** React + TypeScript (strict) + Vite, MUI, React Router, TanStack Query, Vitest.
- **Port:** `3000` (development) / Nginx container (production)
- **Reference:** APPLICATION_CONCEPTION_PLAN V2.1 Sections 21.1, 21.2

## Key Responsibilities
1. **Architecture & State Management:**
   - Feature-based structure (`features/auth`, `features/transfers`, `features/requests`, `features/review`, `features/analytics`).
   - Store access token in memory (never localStorage), silent refresh via httpOnly cookie on app load.
   - Single in-flight refresh promise, retry once on 401.
2. **Role-Based Route Guards:**
   - Public: `/login`, `/register`.
   - `CUSTOMER`: `/dashboard`, `/send`, `/withdraw`, `/requests`, `/history`.
   - `ANALYST`: `/review-queue`, `/cases/:id`, `/analytics`.
   - `ADMIN`: `/users`, `/topup`, `/audit`, `/analytics`, `/system`.
3. **Mock Service Worker (MSW):** Setup mock handlers generated from OpenAPI specs to develop UI before backend endpoints are ready.

## Definition of Done (DoD)
- [ ] Clean modern responsive layout with role-based navigation.
- [ ] Silent JWT refresh working seamlessly.
- [ ] Vitest test suite running in CI.
"@

    9 = @"
## Overview & Architecture Specification
Build the Customer UI views for viewing balances, sending money, and responding to live payment requests.
- **Reference:** APPLICATION_CONCEPTION_PLAN V2.1 Sections 11.5, 11.7, 21.3

## Key Responsibilities
1. **Customer Dashboard:**
   - Display total balance, available balance, and held funds.
   - Recent transactions list with status chips (Completed, Under Review, Declined).
2. **Send Money Flow:**
   - Identifier lookup -> display masked recipient name (`J*** D**`) for confirmation.
   - Generate unique `Idempotency-Key` UUID on form open, reuse on retry.
   - Result screen displaying customer-safe outcome messages (never show fraud probability or risk scores!).
3. **Live Payment Request Pop-Up (CRITICAL):**
   - Poll incoming requests every 5s (`GET /payment-requests?role=incoming&status=PENDING`).
   - Display prominent pop-up modal on any screen with:
     - Requester masked name, amount, note.
     - **Live 2-minute countdown timer** calculated from server `expiresAt` and `serverTime`.
     - Accept and Decline buttons.
     - Close automatically upon timer expiry with message "Request expired".

## Definition of Done (DoD)
- [ ] Customer can lookup receiver, confirm masked name, and send funds.
- [ ] 2-minute live request pop-up renders countdown accurately across browser tabs.
- [ ] Zero risk scores or probability figures exposed to customers.
"@

    10 = @"
## Overview & Architecture Specification
Develop the Fraud Analyst workbench for investigating flagged transactions and submitting human review decisions.
- **Reference:** APPLICATION_CONCEPTION_PLAN V2.1 Sections 11.8, 21.3

## Key Responsibilities
1. **Review Queue Table (`/review-queue`):**
   - List pending cases with: Amount, parties (masked), SLA deadline countdown (24h limit), priority badge, degraded indicator, claimed-by user.
   - Auto-refresh every 15s.
2. **Case Detail Screen (`/cases/:id`):**
   - **Sender & Receiver panels side-by-side:** KYC status, account age, balance, recent transactions.
   - **Model Evidence panel:** Fraud probability (0.00-1.00), uncertainty score, conformal prediction set (`['legit']`, `['fraud']`, or `['legit', 'fraud']`), model version, feature contribution bars.
   - **Action Bar:** Claim case (soft lock), release claim.
   - **Decision Form:** Approve or Reject buttons, mandatory reason textarea (minimum 10 characters), confirmation modal.

## Definition of Done (DoD)
- [ ] Analyst can view queue, claim a case, inspect side-by-side evidence, and submit decision.
- [ ] Reason validation enforces at least 10 characters before submitting.
"@

    11 = @"
## Overview & Architecture Specification
Integrate interactive 2D data visualizations in the ML Analytics dashboard for analysts and administrators.
- **Technology:** Plotly.js (`scattergl` WebGL partial bundle) + Recharts
- **Reference:** APPLICATION_CONCEPTION_PLAN V2.1 Sections 21.3, 21.4

## Key Responsibilities
1. **Embedding Visualization Tab:**
   - Fetch precomputed JSON from `GET /risk/viz/{method}` (`pca`, `tsne`, `umap`).
   - Toggle buttons to switch projection method (PCA, t-SNE, UMAP).
   - Color code points: Legit (blue), Fraud (red). Highlight misclassified errors with distinct markers.
   - Toggle filter to isolate uncertain points (`prediction_set` containing both classes).
   - Rich hover tooltip displaying transaction amount, type, and key features.
2. **Live Decision Statistics Tab:**
   - Distribution chart of Approved vs Rejected vs Under Review.
   - Line chart of review rate and degraded ratio over time.
3. **Model Information Tab:** Model name, version, training date, conformal confidence level (95%).

## Definition of Done (DoD)
- [ ] Plotly renders 5,000+ points smoothly without browser lag.
- [ ] Method toggle smoothly updates coordinates.
"@

    12 = @"
## Overview & Architecture Specification
Consolidate and polish the final README Markdown report serving as the primary academic deliverable for the project.
- **Deadline:** Freeze by January 3, 2027 (Final delivery: January 10, 2027)
- **Reference:** APPLICATION_CONCEPTION_PLAN V2.1 Section 24.4, Enquête Section 1

## Key Responsibilities
1. **Structure & Assembly:**
   - Merge role sections from `docs/readme-sections/`:
     - Role 1: Microservices FinTech Architecture, JWT, Outbox, Invariants.
     - Role 2: Frontend UX, Human-Review Queue, 2D Embeddings.
     - Role 3: Kubernetes deployment, HPA, CI/CD pipeline, Prometheus/Grafana supervision, Chaos experiments.
     - Role 4: PaySim Benchmark, Statistical validation (Friedman/Wilcoxon), Conformal prediction, Locust load tests.
     - Role 5: FastAPI serving, MLflow pipeline, Model registry.
2. **Visual Evidence:** Embed high-resolution screenshots of Grafana dashboards under load, Chaos pod-kill recovery, Locust graphs, and Swagger UI.
3. **Style & Proofreading:** Professional English, clear headings, table of contents, and reproducible setup instructions.

## Definition of Done (DoD)
- [ ] README.md is complete, fully formatted, and contains all required architectural and experimental evidence.
"@

    13 = @"
## Overview & Architecture Specification
Record, edit, and publish the official 5-minute project demonstration video required for final evaluation.
- **Maximum Length:** Exactly 5 minutes (hard limit).
- **Format:** MP4 / YouTube unlisted link in README.

## Video Scenario Timeline (1 minute per chapter):
1. **Min 0:00 - 1:00 (Customer Flow):** Login, dashboard view, send money with instant ML approval.
2. **Min 1:00 - 2:00 (Human Review & Pop-up):** Payment request with 2-min countdown pop-up; suspicious transaction routed to Analyst queue; Analyst reviews side-by-side evidence and approves with reason.
3. **Min 2:00 - 3:30 (Locust Load Test & Auto-scaling):** Split-screen: Locust sending traffic (Normal -> High -> Overload) while Grafana shows HPA scaling pods from 2 to 5 replicas.
4. **Min 3:30 - 4:30 (Chaos Engineering & High Availability):** Pod-kill command executed live in terminal; Prometheus alert triggers; service recovers instantly; call `/admin/ledger/verify` demonstrating 100% money conservation.
5. **Min 4:30 - 5:00 (Conclusion):** GitHub Actions CI/CD green pipeline and wrap up.

## Definition of Done (DoD)
- [ ] 5-minute video recorded, voiceover/captions added, and linked in repository README.
"@

    # --------------------------------------------------------------------------
    # ROLE 3 : DEVOPS / MLOPS
    # --------------------------------------------------------------------------
    14 = @"
## Overview & Architecture Specification
Provision and validate the local Kubernetes development cluster with Ingress and metrics-server.
- **Driver:** Minikube (Docker driver) or Kind
- **Hardware Budget:** 4 CPU cores, 12 GB RAM (after 24 GB upgrade)
- **Reference:** APPLICATION_CONCEPTION_PLAN V2.1 Section 24.1

## Key Responsibilities
1. **Cluster Provisioning:**
   - Execute: `minikube start --cpus=4 --memory=12288 --driver=docker --addons=ingress,metrics-server`
   - Verify metrics-server: `kubectl top nodes` and `kubectl top pods`.
2. **Ingress Controller Configuration:**
   - Ingress controller listens on ports 80/443 and routes hostname `fintech.local`.
3. **Smoke-Test Execution:**
   - Deploy manifests from `k8s/base/_smoke-test/` (nginx 2 replicas, ClusterIP service, Ingress, HPA).
   - Assert `kubectl get hpa` displays CPU percentage (proves metrics-server works).
   - Capture evidence screenshots for the project report.

## Definition of Done (DoD)
- [ ] Minikube starts cleanly with ingress and metrics-server.
- [ ] Smoke-test HPA autoscaler functions properly.
"@

    15 = @"
## Overview & Architecture Specification
Deploy the persistent data layer and ML infrastructure on Kubernetes with proper storage and schema provisioning.
- **Namespace:** `data`
- **Reference:** APPLICATION_CONCEPTION_PLAN V2.1 Sections 4.2, 13.1, 24.1

## Key Responsibilities
1. **PostgreSQL 16 StatefulSet:**
   - PersistentVolumeClaim (PVC) with durable local storage.
   - Mount initialization script to automatically create the 6 schemas: `auth`, `customer`, `transaction`, `risk`, `notification`, `audit`.
   - Set PostgreSQL `max_connections >= 150` to accommodate microservice connection pools.
2. **MinIO Object Storage:**
   - StatefulSet with PVC, provision default bucket `mlflow-artifacts`.
3. **MLflow Tracking Server:**
   - Connect backend store to PostgreSQL (`postgresql://.../mlflow`) and artifact store to MinIO S3 (`s3://mlflow-artifacts`).
4. **RabbitMQ & Mailpit:** Deploy RabbitMQ with management UI and Mailpit SMTP.

## Definition of Done (DoD)
- [ ] PostgreSQL persists data across pod deletions.
- [ ] MLflow UI accessible and able to log model runs and artifacts to MinIO.
"@

    16 = @"
## Overview & Architecture Specification
Write production-grade Kubernetes manifests for all microservices using Kustomize with resource limits and HPA.
- **Reference:** APPLICATION_CONCEPTION_PLAN V2.1 Sections 22.1, 24.1

## Key Responsibilities
1. **Kustomize Architecture:**
   - Structure: `k8s/base/` (common manifests) and `k8s/overlays/dev/` + `k8s/overlays/prod/`.
2. **Deployment Standards per Spring Service:**
   - `startupProbe`: path `/actuator/health/liveness`, failureThreshold 30, periodSeconds 2 (gives 60s cold start time).
   - `livenessProbe`: path `/actuator/health/liveness`, periodSeconds 10.
   - `readinessProbe`: path `/actuator/health/readiness`, periodSeconds 5 (checks DB connection only).
   - Resource requests: CPU 100m, Memory 384Mi | limits: CPU 500m, Memory 640Mi.
   - Graceful termination: `terminationGracePeriodSeconds: 40`.
3. **Horizontal Pod Autoscaler (HPA):**
   - Configure HPA (min 2, max 5 replicas, target CPU 60%) for `api-gateway`, `transaction-service`, `risk-service`, and `ml-serving`.
4. **Unified Ingress (`k8s/ingress/`):**
   - Route `/` to React frontend and `/api/` to API Gateway.

## Definition of Done (DoD)
- [ ] `kubectl apply -k k8s/overlays/dev` deploys entire stack without errors.
- [ ] Zero pod restart loops; startupProbe handles Spring initialization smoothly.
"@

    17 = @"
## Overview & Architecture Specification
Deploy the Prometheus and Grafana monitoring stack via Helm and configure ServiceMonitors for automated scraping.
- **Namespace:** `monitoring`
- **Tooling:** `kube-prometheus-stack` Helm chart
- **Reference:** APPLICATION_CONCEPTION_PLAN V2.1 Sections 22.1, 22.2, Enquête Bloc D

## Key Responsibilities
1. **Helm Deployment:**
   - Deploy `kube-prometheus-stack` with Prometheus, Alertmanager, Grafana, and kube-state-metrics.
2. **ServiceMonitors:**
   - Create ServiceMonitor targeting Spring Boot Actuator: port 8080-8086, path `/actuator/prometheus`, interval 15s.
   - Create ServiceMonitor targeting FastAPI: port 8000, path `/metrics`, interval 15s.
   - Deploy `postgres_exporter` to monitor database connection pool and query performance.
3. **Validation:**
   - Verify in Prometheus web UI (`:9090/targets`) that all microservice targets show state `UP`.

## Definition of Done (DoD)
- [ ] Prometheus scrapes all microservice endpoints every 15s.
- [ ] Grafana accessible with default credentials and Prometheus datasource connected.
"@

    18 = @"
## Overview & Architecture Specification
Implement multi-stage CI/CD GitHub Actions pipelines with quality gates, security scans, and automated rollback.
- **Reference:** APPLICATION_CONCEPTION_PLAN V2.1 Section 24.1, Enquête Bloc B

## Key Responsibilities
1. **CI Validation Pipeline (`.github/workflows/ci.yml`):**
   - Triggers on Pull Requests.
   - Path-based filtering (only build components that changed).
   - Unit and integration tests (Maven verify, Pytest).
   - SonarCloud code quality analysis (enforce >= 70% coverage on domain packages).
   - Security scanning: **Gitleaks** (secret detection) and **Trivy** (vulnerability scanning).
2. **CD Release Pipeline (`.github/workflows/cd.yml`):**
   - Triggers on merge to `main`.
   - Build multi-stage Docker images.
   - Tag and push to GitHub Container Registry: `ghcr.io/oubay-s/fintech-<service>:<sha>` and `:latest`.
3. **Automated Rollback Mechanism:**
   - Deployment step runs `kubectl apply -k k8s/overlays/prod`.
   - Health verification: `kubectl rollout status deployment/<service> --timeout=120s || kubectl rollout undo deployment/<service>`.

## Definition of Done (DoD)
- [ ] PR with secret or failing test is blocked automatically.
- [ ] Push to main builds and pushes Docker images to GHCR.
- [ ] Failed rollout triggers automatic undo.
"@

    19 = @"
## Overview & Architecture Specification
Perform chaos engineering and pod-kill experiments under active load to validate high availability and financial integrity.
- **Reference:** APPLICATION_CONCEPTION_PLAN V2.1 Section 18.3, Enquête Bloc E, Tâche 9

## Key Responsibilities
1. **Experiment Protocol:**
   - Start Locust baseline load (50 RPS).
   - Kill pods deliberately: `kubectl delete pod -l app=transaction-service` and `kubectl delete pod -l app=risk-service`.
   - Simulate network partition or stop ML Serving to trigger Rule R2 fallback.
2. **Measurements & Observations:**
   - Measure recovery time (time until replacement pod serves traffic).
   - Monitor error rate spike on Grafana (must stay < 5%).
   - Verify that stuck transfers are recovered by the 30s background reconciler.
3. **Financial Invariance Proof (CRITICAL):**
   - Call `GET /api/v1/admin/ledger/verify` immediately after chaos test.
   - Validate Invariants I1, I2, I3: Zero money lost, zero funds stuck in hold, zero balance discrepancies.

## Definition of Done (DoD)
- [ ] Documented test report with recovery times, Grafana screenshots, and ledger verification output.
"@

    20 = @"
## Overview & Architecture Specification
Construct the operational Grafana dashboards and configure threshold alert rules required by project specifications.
- **Reference:** APPLICATION_CONCEPTION_PLAN V2.1 Section 22.2, Projet ML-jee Tâche 10

## Key Responsibilities
1. **PrometheusRule Alert Rules:**
   - `HighCPUUsage`: CPU > 80% for 1 minute (Warning).
   - `HighLatency`: p95 latency > 2s for 30s (Warning).
   - `HighErrorRate`: HTTP 5xx errors > 5% for 1 minute (Critical).
   - `ServiceUnavailable`: `up == 0` on core service for 30s (Critical).
   - `HighMLUncertainty`: Review rate > 25% of total traffic for 2 minutes (Warning).
2. **Grafana Dashboards:**
   - **System & K8s Health:** Node CPU/RAM, pod restarts, network I/O, HPA replica count.
   - **Microservice Performance:** Request throughput (RPS), p50/p95/p99 latency, HTTP status breakdown.
   - **FinTech Operations:** Approved vs Rejected vs Under Review transactions, hold duration, ledger topups.
3. **Alertmanager Integration:** Configure notification receiver (Discord/Slack webhook or Mailpit).

## Definition of Done (DoD)
- [ ] Dashboards render live metrics during test runs.
- [ ] Inducing high CPU or killing a service triggers active alert in Alertmanager.
"@

    # --------------------------------------------------------------------------
    # ROLE 4 : ML TRAINING
    # --------------------------------------------------------------------------
    21 = @"
## Overview & Architecture Specification
Clean, explore, and preprocess the PaySim dataset, addressing extreme class imbalance and data leakage.
- **Dataset:** PaySim (confirmed, ~6.3M rows)
- **Reference:** APPLICATION_CONCEPTION_PLAN V2.1 Sections 8, 11.7, 24.2

## Key Responsibilities
1. **Data Understanding & Scoping:**
   - PaySim contains 5 types: `TRANSFER`, `CASH_OUT`, `PAYMENT`, `DEBIT`, `CASH_IN`.
   - **Crucial insight:** Fraud exists ONLY in `TRANSFER` and `CASH_OUT` (0.13% fraud rate).
2. **Preventing Data Leakage:**
   - Avoid trivial rules: PaySim balance arithmetic (`newbalanceDest == oldbalanceDest`) can cause synthetic leakage.
   - Engineer realistic features: `amount`, `sender_old_balance`, `sender_new_balance`, `receiver_old_balance`, `receiver_new_balance`, balance-drain ratio, transaction velocity.
3. **Imbalance Handling:**
   - Implement techniques: SMOTE, undersampling of majority class, and class weighting (`scale_pos_weight` in XGBoost).
4. **Time-Based Evaluation Split:**
   - Use time-based (`step`) and account-disjoint splits to mimic real-world deployment (never random shuffle!).

## Definition of Done (DoD)
- [ ] Reproducible preprocessing pipeline in `ml/common/preprocessing.py`.
- [ ] Feature list and data split documented for the team.
"@

    22 = @"
## Overview & Architecture Specification
Benchmark 5 candidate machine learning classifiers on PaySim using comprehensive evaluation metrics.
- **Algorithms:** Logistic Regression, Random Forest, XGBoost / LightGBM, Linear SVM, Multi-Layer Perceptron (MLP).
- **Reference:** Projet ML-jee Tâche 2, APPLICATION_CONCEPTION_PLAN V2.1 Section 24.2

## Key Responsibilities
1. **Benchmark Execution:**
   - Train all 5 classifiers with identical training/validation splits.
   - Tune hyperparameters using cross-validation.
2. **Evaluation Metrics (Imbalance-Aware):**
   - **PR-AUC (Precision-Recall AUC):** Primary metric for fraud detection!
   - ROC-AUC, F1-Score, Precision, Recall, Specificity.
   - Matthews Correlation Coefficient (MCC).
   - Brier Score (probability calibration quality).
   - Inference latency per sample (milliseconds).
3. **Reporting:**
   - Report primary metrics on the in-scope subset (`TRANSFER` + `CASH_OUT`), with all-types as secondary.
   - Produce Precision-Recall curves and ROC curves for each algorithm.

## Definition of Done (DoD)
- [ ] Comparative Markdown benchmark table with all 8 metrics for each algorithm.
- [ ] Clear justification of the winning model (e.g. XGBoost).
"@

    23 = @"
## Overview & Architecture Specification
Apply rigorous statistical significance testing to validate that the chosen model's superiority is statistically significant.
- **Reference:** Projet ML-jee Tâche 3, APPLICATION_CONCEPTION_PLAN V2.1 Section 24.2

## Key Responsibilities
1. **Repeated Experiments:**
   - Run 10-fold cross-validation or 5x2 CV across 5 distinct random seeds for all models.
2. **Hypothesis Testing:**
   - **Friedman Test:** Non-parametric test across all 5 algorithms to reject null hypothesis $H_0$ (that all models perform equally).
   - **Wilcoxon Signed-Rank Test:** Pairwise post-hoc comparison between the best model (XGBoost) and each competitor.
   - **Holm-Bonferroni Correction:** Control family-wise error rate across multiple pairwise comparisons.
3. **Effect Size & Confidence Intervals:**
   - Calculate 95% confidence intervals for PR-AUC and F1.
   - Compute Cohen's d / Cliff's delta effect sizes.

## Definition of Done (DoD)
- [ ] SciPy/statsmodels script outputs statistical test results (p-values, statistics).
- [ ] Comprehensive results table included in the README report.
"@

    24 = @"
## Overview & Architecture Specification
Implement prediction uncertainty quantification using Conformal Prediction and calibrate the human-review threshold.
- **Reference:** APPLICATION_CONCEPTION_PLAN V2.1 Sections 11.7, 24.2

## Key Responsibilities
1. **Conformal Prediction Implementation:**
   - Implement inductive Split Conformal Prediction or Mondrian (class-conditional) conformal classification.
   - Generates prediction sets with statistical guarantees at significance level $\alpha = 0.05$ (95% confidence).
   - Output prediction sets: `{legit}`, `{fraud}`, or `{legit, fraud}` (uncertain).
2. **Human-Review Threshold Calibration:**
   - Tune the non-conformity threshold so that the human review rate on normal in-scope traffic stays **<= 5%**.
   - Prevents overwhelming fraud analysts while guaranteeing high recall on suspicious cases.
3. **Artifact Packaging:**
   - Package model weights, conformal calibration parameters, and the review threshold into a single MLflow bundle.

## Definition of Done (DoD)
- [ ] Python module returning prediction sets with verified empirical coverage.
- [ ] Review rate verified <= 5% on test set.
"@

    25 = @"
## Overview & Architecture Specification
Compute 2D embedding coordinates using PCA, t-SNE, and UMAP for fraud cluster and error visualization.
- **Reference:** APPLICATION_CONCEPTION_PLAN V2.1 Sections 21.4, 24.2

## Key Responsibilities
1. **Sampling & Projection:**
   - Sample 5,000 to 10,000 representative PaySim transactions (including legit, fraud, and misclassified cases).
   - Standardize features and compute 2D projections using:
     - **PCA** (linear global structure)
     - **t-SNE** (local clustering)
     - **UMAP** (balance of local and global topology)
2. **Export Format (JSON):**
   - Output structured JSON files for each method:
     ```json
     [ { "x": 1.24, "y": -0.85, "true_label": 1, "predicted_label": 1, "is_uncertain": false, "is_error": false, "amount": 1500.0, "type": "TRANSFER" } ]
     ```
   - Place JSON files in `ml/visualization/` for Role 2 to embed into Plotly.js.

## Definition of Done (DoD)
- [ ] `pca.json`, `tsne.json`, and `umap.json` generated and verified.
- [ ] Clear class separation and highlighted error points visible in plots.
"@

    26 = @"
## Overview & Architecture Specification
Author realistic Locust load-testing scenarios simulating payment traffic across 4 distinct operational phases.
- **Technology:** Python Locust
- **Target:** API Gateway public Ingress endpoint (`/api/v1/transfers`)
- **Reference:** APPLICATION_CONCEPTION_PLAN V2.1 Sections 24.1, 24.2, Enquête Bloc E

## Key Responsibilities
1. **Scenario Structure (`locustfile.py`):**
   - Replay realistic PaySim-like transfer requests.
   - Generate fresh `Idempotency-Key` UUID on every request.
   - Include valid JWT authentication header.
2. **4-Stage Load Profile:**
   - **Phase 1 (Normal Load):** 20 concurrent users, ~20 RPS for 5 min (baseline performance).
   - **Phase 2 (High Load):** Ramp to 100 users, ~100 RPS for 5 min (triggers HPA scale-out).
   - **Phase 3 (Overload):** Ramp to 300+ users for 5 min (stress limits, triggers Prometheus latency alerts).
   - **Phase 4 (Recovery):** Step down to 20 users for 5 min (verifies system stabilization and HPA scale-in).
3. **Execution Instructions:** Provide CLI commands to run headless in CI/CD or with web UI.

## Definition of Done (DoD)
- [ ] `locustfile.py` tested locally against API Gateway.
- [ ] Simulates 4 distinct phases with configurable user counts.
"@

    27 = @"
## Overview & Architecture Specification
Analyze load test experimental measurements, documenting system scalability, bottlenecks, and recovery metrics.
- **Reference:** Projet ML-jee Tâche 9, APPLICATION_CONCEPTION_PLAN V2.1 Section 24.2

## Key Responsibilities
1. **Data Collection & Correlation:**
   - Correlate Locust client-side metrics with Prometheus server-side metrics across all 4 load phases.
2. **Key Measured Indicators (The 7 Project Measurements):**
   - 1. Throughput (Requests per Second - RPS)
   - 2. Response latency (p50, p95, p99 in milliseconds)
   - 3. HTTP error rate (%)
   - 4. CPU and memory utilization of pods
   - 5. Number of pod replicas over time
   - 6. HPA scaling reaction time (seconds to spawn new replicas)
   - 7. Recovery time (seconds to return to baseline after overload)
3. **Reporting:**
   - Write comprehensive Markdown analysis chapter with comparative charts for the final report.

## Definition of Done (DoD)
- [ ] Complete measurement table covering all 7 indicators across the 4 load phases.
- [ ] Visual charts embedded in report.
"@

    # --------------------------------------------------------------------------
    # ROLE 5 : ML SERVING
    # --------------------------------------------------------------------------
    28 = @"
## Overview & Architecture Specification
Deliver the formal OpenAPI 3.0 specification contract for the `/predict` model serving endpoint in Week 1.
- **Reference:** APPLICATION_CONCEPTION_PLAN V2.1 Section 17, 24.3
- **Deliverable Path:** `docs/api/ml-predict-openapi.yaml`

## Key Responsibilities
1. **Request Schema (`POST /predict`):**
   - `schema_version`: string (e.g. `\"1.0\"`)
   - `request_id`: UUID string
   - `features`: object containing PaySim features:
     - `type`: string (`TRANSFER`, `CASH_OUT`)
     - `amount`: number
     - `sender_old_balance`: number
     - `sender_new_balance`: number
     - `receiver_old_balance`: number
     - `receiver_new_balance`: number
2. **Response Schema:**
   - `schema_version`: string (`\"1.0\"`)
   - `action`: suggestion string (`ALLOW`, `BLOCK`, `HUMAN_REVIEW`)
   - `fraud_probability`: float between 0.0 and 1.0
   - `uncertainty`: object containing `{ method, confidence_level, prediction_set: [], score }`
   - `model`: object containing `{ name, version, stage }`
   - `inference_ms`: float latency
   - `explanations`: optional array of feature contributions
3. **Coordination:** Freeze contract with Role 1 so Risk Service can code its HTTP client without delays.

## Definition of Done (DoD)
- [ ] `docs/api/ml-predict-openapi.yaml` validated against OpenAPI 3.0 standards.
- [ ] Approved by Role 1.
"@

    29 = @"
## Overview & Architecture Specification
Build the production **FastAPI** model serving microservice implementing `/predict`, health probes, and metrics.
- **Port:** `8000` | **Language:** Python 3.11 | **Framework:** FastAPI + Uvicorn
- **Reference:** APPLICATION_CONCEPTION_PLAN V2.1 Sections 17, 24.3

## Key Responsibilities
1. **Core Endpoints:**
   - `POST /predict`: Implements the OpenAPI contract. Runs model inference. **Target p95 latency < 300ms**.
   - `GET /health/live`: Process liveness probe.
   - `GET /health/ready`: **Readiness probe** — returns HTTP 200 *only after* model weights are loaded and ready.
   - `GET /metrics`: Prometheus metrics (`inference_time_seconds` histogram, request counters).
   - `GET /model-info`: Returns model name, version, stage, metrics summary, conformal level.
   - `GET /viz/{method}`: Serves precomputed static JSON for `pca`, `tsne`, `umap`.
2. **Dockerization:**
   - Multi-stage Dockerfile based on `python:3.11-slim`, running as non-root user `mluser` (UID 1001).
3. **Resilience & Validation:**
   - Pydantic models validating all inputs and outputs. Returns HTTP 422 on malformed features.

## Definition of Done (DoD)
- [ ] FastAPI service passes pytest suite with 100% contract compliance.
- [ ] `/health/ready` indicates model load status.
- [ ] Latency p95 verified under 300ms.
"@

    30 = @"
## Overview & Architecture Specification
Automate the end-to-end reproducible MLOps pipeline with MLflow tracking and Model Registry.
- **Reference:** Projet ML-jee Tâche 5, APPLICATION_CONCEPTION_PLAN V2.1 Section 4.1, 24.3

## Key Responsibilities
1. **Automated Pipeline (`ml/pipeline/run_pipeline.py`):**
   - Stage 1: Data ingestion & preprocessing.
   - Stage 2: Model training & hyperparameter logging.
   - Stage 3: Evaluation & metrics logging (PR-AUC, ROC-AUC, Brier score).
   - Stage 4: Conformal calibration & threshold calculation.
   - Stage 5: Artifact persistence to MinIO S3 backend (`s3://mlflow-artifacts`).
   - Stage 6: Register model in **MLflow Model Registry** under `fraud-detector`.
2. **Promotion Automation:**
   - Promote validated model to stage `Production`.

## Definition of Done (DoD)
- [ ] One command `python ml/pipeline/run_pipeline.py` executes full pipeline.
- [ ] MLflow UI shows complete run with parameters, metrics curves, and registered model.
"@

    31 = @"
## Overview & Architecture Specification
Enable the FastAPI serving service to dynamically load and serve the active `Production` model from MLflow.
- **Reference:** APPLICATION_CONCEPTION_PLAN V2.1 Section 4.1, 17.2

## Key Responsibilities
1. **Model Loader:**
   - On container startup, query MLflow Tracking Server (`http://localhost:5000` or K8s service).
   - Download model artifact matching `models:/fraud-detector/Production`.
   - Fallback: Load local cached model if MLflow server is temporarily unreachable.
2. **Metadata Transparency:**
   - Inject loaded `model_version`, `run_id`, and `stage` into `/model-info` and `/predict` responses.

## Definition of Done (DoD)
- [ ] Promoting a new model version in MLflow updates FastAPI serving after container reload.
"@

    32 = @"
## Overview & Architecture Specification
Build dedicated Grafana dashboards monitoring ML model serving latency, throughput, and prediction distributions.
- **Reference:** APPLICATION_CONCEPTION_PLAN V2.1 Section 22.2, 24.3

## Key Responsibilities
1. **Dashboard Panels:**
   - Model inference latency histogram (p50, p90, p95, p99).
   - Request throughput (requests per second).
   - Prediction distribution: % Legitimate vs % Fraud vs % Uncertain.
   - Uncertainty score distribution over time.
   - Active model name and model version gauge.
2. **Export:**
   - Export dashboard as reusable JSON to `k8s/monitoring/dashboards/ml-serving.json`.

## Definition of Done (DoD)
- [ ] Dashboard imports into Grafana and displays real-time FastAPI metrics.
"@

    33 = @"
## Overview & Architecture Specification
Configure Prometheus alerting rule detecting abnormal spikes in model prediction uncertainty.
- **Reference:** APPLICATION_CONCEPTION_PLAN V2.1 Section 22.2, Projet ML-jee Tâche 10

## Key Responsibilities
1. **Alert Rule Design (`PrometheusRule`):**
   - Name: `HighMLUncertaintyRate`
   - Expression: Alert if the proportion of decisions flagged as `PENDING_REVIEW` (uncertain) exceeds 25% of total decisions over a 5-minute sliding window.
   - Severity: `warning`
2. **Operational Rationale:**
   - High uncertainty indicates data drift, new fraud attack patterns, or broken upstream preprocessing.
   - Triggers investigation before the human review queue becomes completely saturated.

## Definition of Done (DoD)
- [ ] Alert rule YAML created in `k8s/monitoring/alert-rules/ml-uncertainty-alert.yaml`.
- [ ] Verified by simulating an uncertainty spike in Prometheus.
"@

    34 = @"
## Overview & Architecture Specification
Implement automated contract and parity tests between Spring Boot Risk Service and FastAPI serving.
- **Reference:** APPLICATION_CONCEPTION_PLAN V2.1 Section 17.3, 23

## Key Responsibilities
1. **Contract Verification:**
   - Assert all required request and response fields match OpenAPI schema exactly.
   - Test handling of edge cases (empty balance, zero amount, negative values).
2. **Parity Testing:**
   - Verify that passing the same PaySim sample to the offline model and the HTTP `/predict` endpoint yields identical predictions, probabilities, and uncertainty sets.
3. **Error & Timeout Testing:**
   - Simulate 1.5s timeout and verify Risk Service circuit breaker triggers Rule R2 fallback (`degraded=true`).

## Definition of Done (DoD)
- [ ] Automated integration test suite runs and passes in CI.
"@
}

Write-Host "Updating all 34 issues on GitHub repository: $repo..."

foreach ($num in 1..34) {
    if ($issueUpdates.ContainsKey($num)) {
        $body = $issueUpdates[$num]
        $body | gh issue edit $num --repo $repo --body-file - 2>&1 | Out-Null
        Write-Host "Updated Issue #$num successfully!"
    }
}

Write-Host "`nAll 34 issues successfully synchronized with APPLICATION_CONCEPTION_PLAN V2.1!"
