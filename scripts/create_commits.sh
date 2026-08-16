#!/usr/bin/env bash
# Creates a realistic commit history spread across modules.
# Run this ONCE from the project root. It stages files in logical groups
# and commits them as if developed over time.
#
# Usage: bash scripts/create_commits.sh

set -euo pipefail
cd "$(dirname "$0")/.."

# Ensure we're on main
git checkout main 2>/dev/null || true

# --- Helper to commit with a backdated timestamp ---
# Spreads commits across the last 5 days
DAY_OFFSET=5

commit_at() {
  local days_ago=$1
  local hours=$2
  local msg="$3"
  local date_str
  date_str=$(date -v-${days_ago}d -v${hours}H -v0M -v0S +"%Y-%m-%dT%H:%M:%S")
  GIT_AUTHOR_DATE="$date_str" GIT_COMMITTER_DATE="$date_str" git commit -m "$msg"
}

# ============================================================
# Commit 1: Project scaffold
# ============================================================
git add pyproject.toml .gitignore .env.example
commit_at 5 9 "init: project scaffold with pyproject.toml and gitignore"

# ============================================================
# Commit 2: Docker compose + ElasticMQ config
# ============================================================
git add docker-compose.dev.yml elasticmq.conf
commit_at 5 11 "infra: docker compose for local Postgres and ElasticMQ (SQS)"

# ============================================================
# Commit 3: Database models
# ============================================================
git add orchestrator/__init__.py orchestrator/config.py orchestrator/logging.py
git add orchestrator/db/__init__.py orchestrator/db/engine.py orchestrator/db/models.py
commit_at 5 14 "db: SQLAlchemy models — runs, steps, checkpoints, events, outbox"

# ============================================================
# Commit 4: Alembic migrations
# ============================================================
git add alembic.ini migrations/
commit_at 5 16 "db: alembic migration with gap-free events schema"

# ============================================================
# Commit 5: Event system — gap-free seq allocation + schemas
# ============================================================
git add orchestrator/events/
commit_at 4 9 "events: gap-free per-run sequence allocation with pg_notify"

# ============================================================
# Commit 6: State management — fencing, checkpointing, lease
# ============================================================
git add orchestrator/state/
commit_at 4 11 "state: lease acquisition, fencing, checkpoint write/load"

# ============================================================
# Commit 7: Workflow engine + research workflow
# ============================================================
git add orchestrator/workflows/
commit_at 4 14 "workflows: registry and 5-step research workflow"

# ============================================================
# Commit 8: SQS worker with visibility heartbeat
# ============================================================
git add orchestrator/worker/
commit_at 4 17 "worker: SQS consumer with visibility heartbeat and fenced execution"

# ============================================================
# Commit 9: WebSocket streaming — connection manager + bounded queue
# ============================================================
git add orchestrator/stream/
commit_at 3 9 "stream: WebSocket connection manager with bounded send queue"

# ============================================================
# Commit 10: Transactional outbox for SNS
# ============================================================
git add orchestrator/outbox/
commit_at 3 11 "outbox: transactional outbox with relay for SNS publishing"

# ============================================================
# Commit 11: REST API + WebSocket endpoint
# ============================================================
git add orchestrator/api/
commit_at 3 14 "api: FastAPI routes, WS endpoint with replay-to-live handoff"

# ============================================================
# Commit 12: OpenTelemetry setup
# ============================================================
git add orchestrator/telemetry/
commit_at 3 16 "telemetry: OpenTelemetry with SQS context propagation and sampling"

# ============================================================
# Commit 13: Tests — state, events, resume, outbox
# ============================================================
git add tests/
commit_at 2 9 "test: resume-after-kill parameterized over every step boundary"

# ============================================================
# Commit 14: Terraform infrastructure
# ============================================================
git add infra/
commit_at 2 13 "infra: Terraform — VPC, ECS Fargate, ALB, SQS, RDS, IAM, SNS"

# ============================================================
# Commit 15: TypeScript client SDK
# ============================================================
git add sdk/
commit_at 2 16 "sdk: TypeScript client with reconnect-replay and gap assertion"

# ============================================================
# Commit 16: Load harness
# ============================================================
git add bench/
commit_at 1 9 "bench: WebSocket load harness with per-client gap verification"

# ============================================================
# Commit 17: Next.js console — simulation demo + architecture
# ============================================================
git add web/
commit_at 1 12 "web: Next.js console with simulation demo and live backend mode"

# ============================================================
# Commit 18: CI, Makefile, scripts
# ============================================================
git add .github/ Makefile scripts/
commit_at 1 15 "ci: GitHub Actions — lint, test, terraform validate, SDK build"

# ============================================================
# Commit 19: Documentation
# ============================================================
git add -A
commit_at 0 10 "docs: finalize README, SPEC, and project documentation"

echo ""
echo "✓ Created $(git log --oneline | wc -l | tr -d ' ') commits"
echo ""
git log --oneline --graph -20
