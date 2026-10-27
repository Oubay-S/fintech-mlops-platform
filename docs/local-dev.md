# Local Development Guide (Lightweight Infrastructure)

This guide explains how to start, verify, and stop the lightweight local infrastructure supporting **PostgreSQL 16**, **MinIO (S3 object store)**, the **MLflow Tracking Server**, **RabbitMQ (Message Broker)**, and **Mailpit (SMTP catcher)**.

> **Memory Budget:** Configured strictly with container limits to consume **under 1.4 GB RAM total**, ensuring smooth operation even on 8 GB workstations.

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

Docker will:
1. Initialize **PostgreSQL** and automatically create the 6 microservice schemas: `auth`, `customer`, `transaction`, `risk`, `notification`, `audit`.
2. Start **MinIO** and automatically provision the S3 bucket `mlflow-artifacts`.
3. Launch the **MLflow Tracking Server** connected to PostgreSQL and MinIO.
4. Launch **RabbitMQ** with management plugin enabled for asynchronous event streaming.
5. Launch **Mailpit** to catch and display all local development emails.

---

## 3. Verifying Health & Endpoints

### Check Container Status
```bash
make ps
```
*Expected status:* All services should display `Up (healthy)`.

### View Live Logs
```bash
make logs
```

### Access Local Web Interfaces & Credentials

| Service | Protocol / Port | Web UI URL | Default Credentials |
|---------|-----------------|------------|---------------------|
| **MLflow Tracking UI** | HTTP :5000 | [http://localhost:5000](http://localhost:5000) | No auth required |
| **RabbitMQ Management** | HTTP :15672 (AMQP :5672) | [http://localhost:15672](http://localhost:15672) | User: `guest`<br>Password: `guest` |
| **Mailpit (Email Catcher)** | HTTP :8025 (SMTP :1025) | [http://localhost:8025](http://localhost:8025) | No auth required |
| **MinIO Console** | HTTP :9001 (API :9000) | [http://localhost:9001](http://localhost:9001) | User: `minioadmin`<br>Password: `changeme_minio` |
| **PostgreSQL 16** | TCP :5432 | Connection URI below | DB: `fintech`<br>User: `fintech_user`<br>Password: `changeme_postgres` |

#### PostgreSQL Connection String (JDBC):
```
jdbc:postgresql://localhost:5432/fintech?currentSchema=transaction
```
*(Replace `transaction` with `auth`, `customer`, `risk`, `notification`, or `audit` depending on the microservice).*

---

## 4. Stopping the Stack

To stop containers while preserving database, queues, and artifact data in Docker volumes:

```bash
make down
```
*Equivalent command:* `docker compose down`

To completely reset the environment and purge all data (fresh clean install):

```bash
docker compose down -v
```
