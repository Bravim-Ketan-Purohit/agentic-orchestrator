#!/usr/bin/env bash
# Kill the worker at a specific step boundary to test resume-from-checkpoint.
# Usage: ./scripts/kill_worker_at_step.sh [step_number]
# Default kills at step 3.

set -euo pipefail

STEP=${1:-3}
WORKER_PID=$(pgrep -f "orchestrator.worker" | head -1 || true)

if [ -z "$WORKER_PID" ]; then
    echo "No worker process found. Start one with: make worker"
    exit 1
fi

echo "Monitoring worker PID $WORKER_PID, will SIGKILL at step $STEP..."

# Watch the logs for the target step
while true; do
    if docker compose -f docker-compose.dev.yml exec -T postgres \
        psql -U orchestrator -tAc \
        "SELECT COUNT(*) FROM steps WHERE state = 'succeeded'" 2>/dev/null | grep -q "^${STEP}$"; then
        echo "Step $STEP completed. Sending SIGKILL to worker PID $WORKER_PID"
        kill -9 "$WORKER_PID"
        echo "Worker killed. It should resume from checkpoint on restart."
        exit 0
    fi
    sleep 0.1
done
