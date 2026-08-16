#!/usr/bin/env bash
# Start the full local stack: Postgres + ElasticMQ + 2 API instances + worker
# No AWS account needed — everything runs on your machine.
set -euo pipefail

cd "$(dirname "$0")/.."

echo "=== Starting Docker services (Postgres :7602, ElasticMQ :7604) ==="
docker compose -f docker-compose.dev.yml up -d postgres elasticmq

echo "=== Waiting for Postgres..."
until docker compose -f docker-compose.dev.yml exec -T postgres pg_isready -U orchestrator 2>/dev/null; do
  sleep 0.5
done
echo "Postgres ready."

echo "=== Running migrations ==="
alembic upgrade head

echo "=== Starting API instance 1 on :7601 ==="
uvicorn orchestrator.api.app:app --host 0.0.0.0 --port 7601 --reload &
API1_PID=$!

echo "=== Starting API instance 2 on :7605 ==="
uvicorn orchestrator.api.app:app --host 0.0.0.0 --port 7605 &
API2_PID=$!

echo "=== Starting worker (concurrency 4) ==="
python -m orchestrator.worker --concurrency 4 &
WORKER_PID=$!

echo ""
echo "============================================"
echo "  All services running locally:"
echo "  API 1:   http://localhost:7601"
echo "  API 2:   http://localhost:7605"
echo "  Worker:  PID $WORKER_PID"
echo "  Postgres: localhost:7602"
echo "  SQS:     localhost:7604"
echo ""
echo "  Frontend: cd web && npm install && npm run dev"
echo "            → http://localhost:7600"
echo ""
echo "  Press Ctrl+C to stop all."
echo "============================================"

cleanup() {
  echo ""
  echo "Stopping..."
  kill $API1_PID $API2_PID $WORKER_PID 2>/dev/null || true
  wait $API1_PID $API2_PID $WORKER_PID 2>/dev/null || true
  echo "Done."
}
trap cleanup EXIT INT TERM

wait
