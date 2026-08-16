.PHONY: dev up down migrate test lint typecheck fmt api1 api2 worker load ci install web

# === Quick Start ===
# 1. make install     (one-time setup)
# 2. make up          (start Postgres + SQS)
# 3. make migrate     (create tables)
# 4. make dev         (runs both API instances + worker)
# 5. make web         (in another terminal — starts frontend)

# One-time setup
install:
	uv venv --python 3.12
	. .venv/bin/activate && uv pip install -e ".[dev]"
	@echo "\n✓ Python env ready. Run: source .venv/bin/activate"
	@echo "  Then: cd web && npm install"

# Development services (Postgres + ElasticMQ only — no AWS needed)
up:
	docker compose -f docker-compose.dev.yml up -d postgres elasticmq
	@echo "Waiting for Postgres..."
	@until docker compose -f docker-compose.dev.yml exec -T postgres pg_isready -U orchestrator 2>/dev/null; do sleep 0.5; done
	@echo "✓ Services ready"

down:
	docker compose -f docker-compose.dev.yml down

# Database
migrate:
	alembic upgrade head

# Run everything locally (2 API instances + worker)
dev: up migrate
	@echo "\n=== Starting API :7601, API :7605, Worker ==="
	@echo "Press Ctrl+C to stop all\n"
	bash scripts/dev.sh

# Two API instances — required to prove cross-instance fan-out
api1:
	uvicorn orchestrator.api.app:app --host 0.0.0.0 --port 7601 --reload

api2:
	uvicorn orchestrator.api.app:app --host 0.0.0.0 --port 7605

# Worker
worker:
	python -m orchestrator.worker --concurrency 4

# Frontend (Next.js on :7600)
web:
	cd web && npm run dev

# Testing
test:
	pytest -q

test-integration:
	pytest -q -m integration

test-chaos:
	pytest -q -m chaos

# Code quality
lint:
	ruff check .

fmt:
	ruff format .
	ruff check --fix .

typecheck:
	mypy orchestrator/state orchestrator/stream orchestrator/worker orchestrator/events

# Load testing (raise ulimit first!)
load:
	@echo "Raise file descriptors first: ulimit -n 65536"
	python -m bench.wsload --sessions 500 --ramp 30 --hold 300 --reconnect-rate 0.05

# CI (matches GitHub Actions)
ci: lint typecheck test
