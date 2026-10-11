# FinTech MLOps Platform

> **High-Availability MLOps FinTech Platform** — Real-time fraud detection and risk scoring powered by Spring Boot microservices, FastAPI ML serving, Kubernetes orchestration, end-to-end CI/CD, and Prometheus/Grafana intelligent monitoring.

**Academic Project — LSI 2026/2027 — Final Deadline: January 10, 2027**

---

## 🏗️ Architecture Overview

<!-- Architecture diagram to be updated with Mermaid or asset in docs/screenshots/ -->

```
[Client Web Browser] → [React Dashboard]
                               ↓
                      [API Gateway :8080]
                        ↓    ↓    ↓
                 [Auth] [Customer] [Transaction]
                                       ↓
                                  [Risk Service] → [FastAPI /predict :8000]
                                       ↓                     ↓
                               [Notification]           [MLflow :5000]
                               [Audit]
                                       ↓
                          [Prometheus + Grafana]
```

---

## 👥 Team Roles & Responsibilities

| # | Role | Owner | README Section |
|---|------|-------|----------------|
| 1 | Backend (Spring Boot) | *TBD* | [→ Backend Documentation](docs/readme-sections/) |
| 2 | Frontend & Delivery | *TBD* | [→ Frontend Documentation](docs/readme-sections/) |
| 3 | DevOps / MLOps | @Oubay-S | [→ DevOps/MLOps Documentation](docs/readme-sections/) |
| 4 | ML Training | *TBD* | [→ ML Training Documentation](docs/readme-sections/) |
| 5 | ML Serving | *TBD* | [→ ML Serving Documentation](docs/readme-sections/) |

---

## 📂 Repository Layout

```
fintech-mlops-platform/
├── services/           # Spring Boot microservices (Role 1 & Role 2)
├── ml/                 # ML training, serving, and pipeline (Roles 4 & 5)
├── frontend/           # React dashboard & visualization UI (Role 2)
├── k8s/                # Kubernetes manifests and overlays (Role 3)
├── infra/              # Local cluster configs, setup scripts (Role 3)
├── scripts/            # Automation & deployment scripts
├── docs/               # Team conventions, guides, and README sections
├── docker-compose.yml  # Lightweight local dev stack (Postgres, MinIO, MLflow)
└── Makefile            # Shortcut commands for local development
```

---

## 🚀 Quickstart (Local Development)

```bash
# 1. Clone the repository
git clone https://github.com/Oubay-S/fintech-mlops-platform.git
cd fintech-mlops-platform

# 2. Copy the environment template
cp .env.example .env
# Edit .env with your local settings if needed

# 3. Start local development infrastructure (Postgres, MinIO, MLflow)
make up

# 4. Stream service logs
make logs
```

For detailed guidance, see [docs/local-dev.md](docs/local-dev.md).

---

## 📖 Role-Specific Documentation

### Role 1 — Backend (Spring Boot)
<!-- Authored by Role 1. See docs/readme-sections/ -->
*To be completed.*

### Role 2 — Frontend & Delivery
<!-- Authored by Role 2. See docs/readme-sections/ -->
*To be completed.*

### Role 3 — DevOps / MLOps
<!-- Authored by Role 3 (@Oubay-S). See docs/readme-sections/ -->
*To be completed.*

### Role 4 — ML Training
<!-- Authored by Role 4. See docs/readme-sections/ -->
*To be completed.*

### Role 5 — ML Serving
<!-- Authored by Role 5. See docs/readme-sections/ -->
*To be completed.*

---

## 📏 Engineering Standards & Team Workflow

- **Issues & PR Workflow:** [docs/workflow-guide.md](docs/workflow-guide.md) — Step-by-step guide on picking issues, branching, and linking PRs (`Closes #ID`).
- **Engineering Conventions:** [docs/conventions.md](docs/conventions.md) — Network ports, Docker images standard, health probes, and Week 1 decisions.
- **Contributing Guidelines:** [CONTRIBUTING.md](CONTRIBUTING.md) — Git commit standards, branch naming, and security requirements.

---

## 📄 License

Academic project — All rights reserved.
