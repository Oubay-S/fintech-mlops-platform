# Local Development Guide (Lightweight Infrastructure)

This guide explains how to start, verify, and stop the lightweight local infrastructure supporting **PostgreSQL**, **MinIO (S3 object store)**, and the **MLflow Tracking Server**.

> **Memory Budget:** Configured strictly with container limits to consume **under 1.5 GB RAM total**, ensuring smooth operation on 8 GB workstations.

---

## 1. Prerequisites

1. **Docker Desktop** installed and running (with WSL2 integration enabled on Windows).
2. Local environment configuration file:
   ```bash
   cp .env.example .env
   ```
   *(Adjust passwords in `.env` if desired; `.env` is ignored by Git and never committed).*

---

## 2. Starting the Stack

From the root of the repository:

```bash
make up
```
*Equivalent command:* `docker compose up -d`

Docker will pull the images, initialize the databases, verify MinIO health, create the default bucket (`mlflow-artifacts`), and launch MLflow.

---

## 3. Verifying Health & Endpoints

### Check Container Status
```bash
make ps
```
*Expected status:* All services (`fintech-postgres`, `fintech-minio`, `fintech-mlflow`) should display `Up (healthy)`.

### View Live Logs
```bash
make logs
```

### Access Local Web Interfaces

| Service | URL | Credentials |
|---------|-----|-------------|
| **MLflow UI** | [http://localhost:5000](http://localhost:5000) | None required |
| **MinIO Console** | [http://localhost:9001](http://localhost:9001) | User: `minioadmin`<br>Password: `changeme_minio` (from `.env`) |
| **PostgreSQL** | `localhost:5432` | DB: `fintech`<br>User: `fintech_user`<br>Password: `changeme_postgres` |

---

## 4. Stopping the Stack

To stop containers while preserving database and artifact data in Docker volumes:

```bash
make down
```
*Equivalent command:* `docker compose down`

To completely reset the environment and purge all data:

```bash
docker compose down -v
```
