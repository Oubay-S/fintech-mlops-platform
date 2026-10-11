# Makefile — FinTech MLOps Platform (dev local)
# Usage: make up | make down | make logs

.PHONY: up down logs ps

## Lancer l'infra de dev (Postgres, MinIO, MLflow)
up:
	docker compose up -d

## Arrêter l'infra de dev
down:
	docker compose down

## Voir les logs en temps réel
logs:
	docker compose logs -f

## État des conteneurs
ps:
	docker compose ps
