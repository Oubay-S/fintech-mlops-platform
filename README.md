# FinTech MLOps Platform

> **High-Availability MLOps FinTech Platform** — Détection de fraude en temps réel avec microservices Spring Boot, ML servi par FastAPI, déploiement Kubernetes, CI/CD et monitoring Prometheus/Grafana.

**Projet académique — LSI 2026/2027 — Deadline : 10 janvier 2027**

---

## 🏗️ Architecture

<!-- TODO: Ajouter le diagramme d'architecture (Mermaid ou image dans docs/screenshots/) -->

```
[Client] → [React Dashboard]
                ↓
         [API Gateway :8080]
           ↓    ↓    ↓
    [Auth] [Customer] [Transaction]
                          ↓
                     [Risk Service] → [FastAPI /predict :8000]
                          ↓                    ↓
                  [Notification]          [MLflow :5000]
                  [Audit]
                          ↓
              [Prometheus + Grafana]
```

---

## 👥 Équipe et rôles

| # | Rôle | Responsable | Section README |
|---|------|-------------|----------------|
| 1 | Backend (Spring Boot) | *À compléter* | [→ Backend](docs/readme-sections/) |
| 2 | Frontend & Livraison | *À compléter* | [→ Frontend](docs/readme-sections/) |
| 3 | DevOps / MLOps | @Oubay-S | [→ DevOps](docs/readme-sections/) |
| 4 | ML Training | *À compléter* | [→ ML Training](docs/readme-sections/) |
| 5 | ML Serving | *À compléter* | [→ ML Serving](docs/readme-sections/) |

---

## 📂 Structure du dépôt

```
fintech-mlops-platform/
├── services/           # Microservices Spring Boot (Rôle 1)
├── ml/                 # ML training, serving, pipeline (Rôles 4 & 5)
├── frontend/           # React dashboard (Rôle 2)
├── k8s/                # Manifests Kubernetes (Rôle 3)
├── infra/              # Config cluster, scripts d'installation
├── scripts/            # Scripts utilitaires
├── docs/               # Documentation par rôle
├── docker-compose.yml  # Dev local (Postgres, MinIO, MLflow)
└── Makefile            # Commandes raccourcies
```

---

## 🚀 Démarrage rapide

```bash
# 1. Cloner le dépôt
git clone https://github.com/Oubay-S/fintech-mlops-platform.git
cd fintech-mlops-platform

# 2. Copier la config d'environnement
cp .env.example .env
# Modifier .env avec vos valeurs locales

# 3. Lancer l'infrastructure de dev
make up

# 4. Vérifier
make logs
```

Voir [docs/local-dev.md](docs/local-dev.md) pour les détails.

---

## 📖 Documentation par rôle

### Rôle 1 — Backend (Spring Boot)
<!-- Section rédigée par le Rôle 1. Voir docs/readme-sections/ -->
*À compléter.*

### Rôle 2 — Frontend & Livraison
<!-- Section rédigée par le Rôle 2. Voir docs/readme-sections/ -->
*À compléter.*

### Rôle 3 — DevOps / MLOps
<!-- Section rédigée par le Rôle 3 (@Oubay-S). Voir docs/readme-sections/ -->
*À compléter.*

### Rôle 4 — ML Training
<!-- Section rédigée par le Rôle 4. Voir docs/readme-sections/ -->
*À compléter.*

### Rôle 5 — ML Serving
<!-- Section rédigée par le Rôle 5. Voir docs/readme-sections/ -->
*À compléter.*

---

## 📏 Conventions

Voir [docs/conventions.md](docs/conventions.md) et [CONTRIBUTING.md](CONTRIBUTING.md).

---

## 📄 Licence

Projet académique — Tous droits réservés.
