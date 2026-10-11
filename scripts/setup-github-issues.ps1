# PowerShell script to initialize labels, milestones, and issues on GitHub

$repo = "Oubay-S/fintech-mlops-platform"
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")

$m1 = "Month 1 (Oct 7 - Nov 7, 2026): Foundations"
$m2 = "Month 2 (Nov 8 - Dec 7, 2026): Integration"
$m3 = "Month 3 (Dec 8, 2026 - Jan 10, 2027): Hardening & Delivery"

$issues = @(
    # --- Role 1 ---
    @{ title = "[Role 1] Setup API Gateway with routing and JWT validation filter"; milestone = $m1; label = "role-1"; body = "Configure Spring Cloud Gateway with routing rules to auth, customer, transaction, and risk services, and JWT header verification." },
    @{ title = "[Role 1] Implement Auth Service with user registration and JWT token generation"; milestone = $m1; label = "role-1"; body = "Implement user authentication endpoints (login, register), BCrypt password hashing, and signed JWT issuance." },
    @{ title = "[Role 1] Implement Customer & Transaction services with REST APIs and Postgres persistence"; milestone = $m1; label = "role-1"; body = "CRUD REST endpoints for customers and transactions backed by PostgreSQL database tables." },
    @{ title = "[Role 1] Containerize all Spring Boot services with multi-stage Dockerfiles"; milestone = $m1; label = "role-1"; body = "Create optimized multi-stage Dockerfiles for all Spring Boot services following the project conventions checklist." },
    @{ title = "[Role 1] Implement Risk Service integrating business rules and calling FastAPI /predict"; milestone = $m2; label = "role-1"; body = "Evaluate incoming transactions by calling the /predict endpoint, applying uncertainty thresholds (allow, block, or human review)." },
    @{ title = "[Role 1] Implement Notification & Audit services for decision tracking"; milestone = $m2; label = "role-1"; body = "Record all transaction evaluations in the audit ledger and send alert notifications for blocked or reviewed transactions." },
    @{ title = "[Role 1] Add /actuator/health, probes, and Prometheus micrometer to all services"; milestone = $m2; label = "role-1"; body = "Add micrometer-registry-prometheus dependency and configure health and metrics endpoints for Kubernetes and Prometheus scraping." },

    # --- Role 2 ---
    @{ title = "[Role 2] Initialize React application with responsive layout and navigation"; milestone = $m1; label = "role-2"; body = "Setup React dashboard with a clean component structure, modern styling, and navigation for financial operations." },
    @{ title = "[Role 2] Implement Authentication and Transaction monitoring views"; milestone = $m1; label = "role-2"; body = "Build login screen, JWT token storage, and live transaction list with status badges (Approved, Blocked, Review)." },
    @{ title = "[Role 2] Build Human-Review Queue for uncertain fraud predictions"; milestone = $m2; label = "role-2"; body = "Provide an interactive reviewer interface where compliance analysts can manually approve or reject flagged transactions." },
    @{ title = "[Role 2] Integrate 2D embedding visualizations (PCA, t-SNE, UMAP)"; milestone = $m2; label = "role-2"; body = "Display clusters, outliers, fraud separation, and misclassified transactions from data computed by Role 4." },
    @{ title = "[Role 2] Consolidate and edit final README report from all role sections"; milestone = $m3; label = "role-2"; body = "Assemble all role-specific documentation into a cohesive, high-quality final README Markdown report." },
    @{ title = "[Role 2] Record, edit, and publish the 5-minute final project demo video"; milestone = $m3; label = "role-2"; body = "Produce a concise, professional 5-minute demo video covering real-time fraud scoring, human review, K8s auto-scaling, and Grafana monitoring." },

    # --- Role 3 ---
    @{ title = "[Role 3] Provision local Kubernetes cluster with Ingress and metrics-server"; milestone = $m1; label = "role-3"; body = "Setup minikube/kind cluster with ingress controller and metrics-server enabled for HPA support." },
    @{ title = "[Role 3] Deploy PostgreSQL StatefulSet, MinIO storage, and MLflow tracking server on K8s"; milestone = $m1; label = "role-3"; body = "Deploy persistent data layer and MLflow tracking server on Kubernetes with PVCs and ConfigMaps." },
    @{ title = "[Role 3] Configure K8s Deployments, ConfigMaps, Secrets, and HPA for all services"; milestone = $m2; label = "role-3"; body = "Write Kustomize manifests for all microservices with probes, resource limits, and Horizontal Pod Autoscalers." },
    @{ title = "[Role 3] Deploy kube-prometheus-stack and configure ServiceMonitors"; milestone = $m2; label = "role-3"; body = "Deploy Prometheus, Grafana, and Alertmanager via Helm, and create ServiceMonitors for Spring Boot and FastAPI." },
    @{ title = "[Role 3] Implement GitHub Actions CI/CD pipelines with SonarCloud, Trivy, and automated rollback"; milestone = $m2; label = "role-3"; body = "Build multi-stage GitHub Actions workflows for tests, security scans, Docker build/push, and zero-downtime deployment." },
    @{ title = "[Role 3] Execute Pod-Kill & High-Availability experiments and document recovery times"; milestone = $m3; label = "role-3"; body = "Simulate chaos events by killing pods/services, measuring recovery time and service continuity with Prometheus evidence." },
    @{ title = "[Role 3] Build infrastructure Grafana dashboards and configure threshold alert rules"; milestone = $m3; label = "role-3"; body = "Create dashboards for system health, K8s cluster, and microservice latency, plus alert rules for CPU > 80% and latency > 2s." },

    # --- Role 4 ---
    @{ title = "[Role 4] Select, explore, and clean financial fraud dataset with class imbalance handling"; milestone = $m1; label = "role-4"; body = "Evaluate candidate fraud datasets, perform preprocessing, and implement class imbalance techniques (SMOTE, class weighting)." },
    @{ title = "[Role 4] Benchmark classifiers: Logistic Regression, Random Forest, XGBoost, SVM, and MLP"; milestone = $m1; label = "role-4"; body = "Benchmark multiple algorithms across Accuracy, Precision, Recall, F1, ROC-AUC, PR-AUC, MCC, and inference latency." },
    @{ title = "[Role 4] Perform statistical validation tests (Friedman, Wilcoxon, Holm correction)"; milestone = $m2; label = "role-4"; body = "Execute repeated cross-validation experiments and compute statistical hypothesis tests to validate model superiority." },
    @{ title = "[Role 4] Implement Uncertainty Quantification and define review threshold"; milestone = $m2; label = "role-4"; body = "Implement prediction uncertainty (probability calibration, conformal prediction) and specify human review cutoff." },
    @{ title = "[Role 4] Compute PCA, t-SNE, and UMAP embeddings for fraud clusters and errors"; milestone = $m2; label = "role-4"; body = "Generate 2D coordinate projections and misclassified sample points for Role 2 to render in the dashboard." },
    @{ title = "[Role 4] Author Locust load testing scenarios (Normal -> High -> Overload -> Recovery)"; milestone = $m3; label = "role-4"; body = "Write Python Locust scripts simulating realistic payment traffic across 4 distinct load phases." },
    @{ title = "[Role 4] Analyze load test measurements (throughput, latency, error rate, scaling times)"; milestone = $m3; label = "role-4"; body = "Produce statistical analysis and graphs of system behavior under load, autoscaling reactions, and recovery times." },

    # --- Role 5 ---
    @{ title = "[Role 5] Provide OpenAPI contract specification for /predict endpoint in Week 1"; milestone = $m1; label = "role-5"; body = "Define the formal OpenAPI schema for /predict (prediction, probability, uncertainty, model_version) for team alignment." },
    @{ title = "[Role 5] Build FastAPI model serving service with /predict, /health, and /metrics endpoints"; milestone = $m1; label = "role-5"; body = "Develop the FastAPI microservice exposing prediction endpoints, health status, and Prometheus instrumentation." },
    @{ title = "[Role 5] Automate end-to-end MLflow pipeline: Training -> Evaluation -> Statistical Test -> Registry"; milestone = $m2; label = "role-5"; body = "Orchestrate automated Python pipeline saving artifacts, metrics, and promoting top-performing model to Production registry." },
    @{ title = "[Role 5] Integrate dynamic model loading from MLflow Model Registry in FastAPI"; milestone = $m2; label = "role-5"; body = "Enable FastAPI service to dynamically download and serve the latest Production model from MLflow." },
    @{ title = "[Role 5] Build Grafana dashboards for ML inference latency, throughput, and uncertainty"; milestone = $m2; label = "role-5"; body = "Construct dedicated Grafana dashboards displaying model inference speed, request rate, and prediction uncertainty distribution." },
    @{ title = "[Role 5] Configure alert rule: high uncertainty rate exceeding threshold for human review"; milestone = $m3; label = "role-5"; body = "Define Prometheus/Alertmanager rule alerting when prediction uncertainty rate spikes above normal operational bounds." },
    @{ title = "[Role 5] Write contract and integration tests between Spring Boot Risk service and FastAPI"; milestone = $m3; label = "role-5"; body = "Author automated integration tests validating schema consistency and error handling between Risk service and FastAPI." }
)

# Fetch existing issues titles to avoid duplicates
$existing = (gh issue list --repo $repo --limit 100 --json title | ConvertFrom-Json).title

foreach ($i in $issues) {
    if ($existing -contains $i.title) {
        Write-Host "Already exists: $($i.title)"
        continue
    }
    gh issue create --repo $repo --title $i.title --body $i.body --label $i.label --milestone $i.milestone
    Write-Host "Created: $($i.title)"
}

Write-Host "`nAll issues verified and created!"
