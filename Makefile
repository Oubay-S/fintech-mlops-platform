# Makefile — FinTech MLOps Platform (Local Development)
# Usage: make up | make down | make logs | make ps

.PHONY: up down logs ps

## Start local development stack (Postgres, MinIO, MLflow)
up:
	docker compose up -d

## Stop local development stack
down:
	docker compose down

## Follow logs in real time
logs:
	docker compose logs -f

## Check container status
ps:
	docker compose ps
