# CLAUDE.md — Stateful Agentic Orchestrator

Operating instructions for a Claude Code session in this repo. Read `SPEC.md` before writing code —
especially §1 (why "no dropped connections" requires sequence numbers) and §3 (fan-out without adding
Redis). `ROADMAP.md` has the order.

## What this is

An orchestrator for long-running agent workflows: SQS-buffered jobs, per-step checkpoints in Postgres,
partial reasoning streamed over WebSockets with gap-free replay, deployed on ECS via Terraform. It exists
to prove one resume bullet, quoted in `SPEC.md` §1.

## Hard rules

1. **Stay inside this directory.** Independent git repo; the parent is deliberately not a repo and seven
   sibling projects sit beside it. Never read, write, or `git` above `agentic-orchestrator/`.
2. **Every event gets a gap-free per-run sequence number**, allocated in the same transaction that writes
   the event. This is what makes the headline claim provable. Never use a global sequence — rolled-back
   transactions leave holes, and a hole is indistinguishable from a dropped message.
3. **Don't add Redis without asking.** Postgres `LISTEN/NOTIFY` over an append-only events table is the
   specified fan-out mechanism, and it keeps the stack matching the resume line. If measurements show it
   can't carry the load, that's a finding to report — and a resume edit — not a silent dependency.
4. **NOTIFY carries a signal, never a payload.** Events are read from the table. Always add the slow-poll
   fallback so a missed notification degrades to latency, not loss.
5. **Bound every per-connection send queue.** On overflow, close with a reconnect code. Unbounded buffering
   means one slow client can OOM an instance.
6. **Never invent a measurement.** `[N]` comes from a committed run in `bench/results/` with hardware,
   topology, and hold duration recorded.
7. **Never touch the resume.** Different repo. Don't edit the `.tex`, don't uncomment the GitHub link.
8. **Cloud spend is the user's decision.** Never `terraform apply` to AWS without asking. `make load-cloud`
   must destroy on failure paths too.
9. **Keys in `.env` only**, `.env.example` committed empty. Validate `Origin` on the WS handshake — WebSockets
   are not covered by CORS and this is the standard miss.

## Environment (this machine: arm64 macOS, 11 cores, 18 GB)

`python3` on the PATH is **3.8.10 and unusable here**. Use `uv` (0.12 installed):

```bash
uv venv --python 3.12
source .venv/bin/activate
uv pip install -e ".[dev]"
```

Services (Docker 28 + compose v2.33):

```bash
docker compose -f docker-compose.dev.yml up -d       # Postgres + ElasticMQ (SQS-compatible)
alembic upgrade head
```

ElasticMQ or LocalStack for local SQS — pick one, pin it, and keep the client code talking plain boto3 so
the only difference in AWS is the endpoint URL.

**Before any load test**, raise the descriptor limit or you'll measure the limit instead of the code:

```bash
ulimit -n 65536      # per shell; record the value in the result manifest
```

Terraform 1.14.4 is installed. Node 22 / npm 10 for `web/` (M6).

## Ports — this project owns 7600–7699

Up to eight sibling projects may run at once. Never bind outside this block; never bind :3000, :5432,
:8000, :9324.

| Port | Use |
| --- | --- |
| 7600 | `web/` Next.js console (`next dev -p 7600`) |
| 7601 | API instance 1 |
| 7605 | API instance 2 — required, it's how cross-instance fan-out is proven |
| 7602 | Postgres (→ 5432) |
| 7603 | reserved (Redis, only if §3 forces it — ask first) |
| 7604 | ElasticMQ / LocalStack SQS |

Run **two** API instances in dev from M2 onward. A single instance makes the fan-out bug invisible, and
then it surfaces on ECS where it's much harder to debug.

## Commands

```bash
uvicorn orchestrator.api.app:app --port 7601 --reload
uvicorn orchestrator.api.app:app --port 7605            # second instance, same DB
python -m orchestrator.worker --concurrency 4
python -m bench.wsload --sessions 2000 --ramp 60s --hold 10m --reconnect-rate 0.05
./scripts/kill_worker_at_step.sh                        # resume-from-checkpoint demo
pytest -q ; pytest -q -m integration ; pytest -q -m chaos
terraform -chdir=infra fmt -check && terraform -chdir=infra validate
```

## Conventions

- Python 3.12, async throughout, full type hints. `mypy --strict` on `orchestrator/state`,
  `orchestrator/stream`, `orchestrator/worker`. Ruff for lint + format.
- asyncpg or SQLAlchemy async. Every step commit is **one** transaction covering the `steps` row, the
  `checkpoints` row, and the events — never three separate commits.
- Pydantic v2 for event payloads and API schemas. Event `kind` is a closed enum; a new kind is a schema
  change with a migration, not a free-form string.
- Workflows are declared in code under `orchestrator/workflows/`, each step a pure-ish function taking
  state and returning state plus events. A step that reaches outside that contract can't be checkpointed.
- Structured logs with `run_id`, `step_id`, `attempt`, `fence`, `seq` on every line in a run's path.
- Tests: pytest + pytest-asyncio. Chaos tests use real Postgres and real local SQS — no mocks. The
  resume-after-kill test parameterises over **every** step boundary, not just the first.
- Commits: imperative, ≤ 72 chars, scoped — `stream: replay from last_seq before going live`.
- Git identity is already set for this repo (`bravimpurohit1305@gmail.com`). Leave it.

## Definition of done, and when to stop

Milestones per `SPEC.md` §10. CI green on push; `terraform fmt`/`validate` in CI, `plan` excluded.

**Stop and ask the user** when:

- It's time to spend money on AWS (M5, and the ECS/Terraform claim). Give the cost estimate first.
- `LISTEN/NOTIFY` measurably can't carry the target load — report the ceiling you measured, then let the
  user decide between Redis (and a resume stack-line edit) and a lower `[N]`.
- The load harness itself is the bottleneck and splitting across hosts is needed.
- A `SPEC.md` requirement looks wrong, or you want a dependency it doesn't name.

Report honestly, with the conditions attached: "2 400 sessions held 12 min across 2 Fargate tasks, 0 seq
gaps, 118 reconnects all replayed clean, delivery lag p95 41 ms, ulimit 65536" is the deliverable. "Handles
thousands of connections" is not.

---

## Extended stack additions (2026-08-17)

See `SPEC.md` §12–13. Gains: **AWS SNS** with a transactional outbox, a **TypeScript client SDK**,
**OpenTelemetry**. Deliberately little else — the claim is about *not dropping connections*, and every extra
moving part is another thing that can drop one. Restraint here is the engineering call; say so in the README.

**New ports** (same 7600–7699 block): `7606` Jaeger UI · `7607` OTel Collector gRPC · `7608` LocalStack SNS.

**New prerequisites:** `opentelemetry-sdk` + FastAPI/asyncpg/boto3 instrumentation. For the SDK: a `sdk/`
workspace with `tsup` or `tsc` build, `vitest`, and type generation from the server's event schemas.

**New hard rules:**

10. **SNS publishes only after the terminal-state transaction commits** — via a transactional outbox with a
    relay, never a `publish()` inside or beside the transaction. A rolled-back transaction that already
    announced success is the classic dual-write bug, and there must be a test for it.
11. **The SDK asserts gap-free delivery and throws on an unfillable gap.** A client that silently continues
    past a gap makes the headline claim unverifiable from the consumer side, which defeats the purpose.
12. **`web/` consumes the SDK**, not its own WebSocket code. That's also how the SDK gets tested properly.
13. **Event types are generated from the server schemas**, never hand-maintained. Hand-written duplicates
    drift, and a drifted event union is a runtime failure in a typed client.
14. **Trace context propagates through SQS message attributes**, so worker spans attach to the API request's
    trace. Retries use **span links**, not fresh root traces.
15. **Tracing is sampled, and exporters are off for the headline load run.** At the target session count,
    tracing every event is more telemetry than payload. Record the measured overhead.
