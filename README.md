# Stateful Agentic Orchestrator

Long-running agent workflows: **SQS-buffered jobs**, **state in PostgreSQL**, partial reasoning
**streamed over WebSockets**, stack provisioned as **Terraform IaC**.

**Stack:** FastAPI · WebSockets · AWS (ECS, SQS) · PostgreSQL · Terraform
**Resume target:** `Bravim_Purohit_Backend_Engineer.tex` → Projects & Publications
**Role:** Backend Engineer

---

## The claim this repo must prove

> Long-running agent workflows: SQS-buffered jobs, state in PostgreSQL, partial reasoning streamed over
> WebSockets, stack provisioned as Terraform IaC. Sustained **[N]** concurrent streaming sessions
> without dropped connections in load tests.

This is a **backend** project that happens to run agents. The interview questions will be about
connection lifecycle, state durability, and horizontal scaling — not about prompting. Build it that way.

## Benchmarks this repo owes the resume

| Metric | Resume placeholder | Measured | Method |
| --- | --- | --- | --- |
| Concurrent streaming sessions | `[N]` sustained, zero drops | — | TBD |

Define before measuring:

- **"Sustained"** — for how long? 60 seconds of 500 connections is not the same claim as an hour.
- **"Without dropped connections"** — measured how? Every client must verify it received a complete,
  ordered event sequence. Counting open sockets proves nothing; a socket can be open and starving.
- **Instance count and size.** Connections-per-instance is the number that actually characterizes the
  system. State the ECS task count and CPU/memory.
- **What the agent was doing.** Idle heartbeat connections are cheap; connections streaming tokens from
  live LLM calls are not. Report the real workload.

**Do not uncomment** the GitHub link at `Bravim_Purohit_Backend_Engineer.tex:134` until this is filled
and the repo is public.

## Architecture

```
 client ──WS──┐
              ▼
    ┌─────────────────────┐   enqueue    ┌─────────┐
    │  FastAPI (ECS task) │ ───────────► │   SQS   │
    │  WS connection mgr  │              └────┬────┘
    └──────────┬──────────┘                   │
               │                              ▼
               │                    ┌──────────────────┐
               │  pub/sub           │  worker (ECS)    │
               │  fan-out           │  agent loop      │
               ▼                    │  step → persist  │
    ┌─────────────────────┐         └────────┬─────────┘
    │  Redis pub/sub      │◄─────── emits ───┘
    │  (cross-instance)   │         step events
    └─────────────────────┘                  │
                                             ▼
                              ┌──────────────────────────┐
                              │ PostgreSQL               │
                              │ run state, step history, │
                              │ checkpoints (resumable)  │
                              └──────────────────────────┘
```

## The three problems worth solving

**1. The connection and the work are decoupled.** A client's WebSocket lands on one ECS task; the worker
executing its run is somewhere else entirely. Events must reach the right connection across instances —
hence Redis pub/sub. Get this wrong and it works perfectly on one instance and fails the moment you
scale out.

**2. Reconnection.** Long-running means the client *will* disconnect mid-run. The run must continue
server-side, and a reconnecting client must be able to replay what it missed. That requires persisted,
sequenced step events — not fire-and-forget broadcasts. This is the feature that separates a demo from
a system.

**3. Resumability.** If a worker dies mid-run, state in PostgreSQL should let another worker pick up
from the last checkpoint. Decide the granularity of a checkpoint (per step, presumably) and what makes
a step idempotent on retry.

## State model

Borrow LangGraph's insight and keep it boring: **state is a serializable dict** passed node to node,
checkpointed after every step. Serializable state is what makes the run resumable, inspectable, and
debuggable. Anything holding a live object reference or an open handle in state is not resumable — that
constraint should drive the design.

## Getting started

```bash
python -m venv .venv && source .venv/bin/activate   # needs Python 3.11+
pip install -r requirements.txt
cp .env.example .env
docker compose up -d                                # Postgres + Redis + SQS (elasticmq/localstack)
alembic upgrade head
pytest -q
uvicorn app.main:app --reload
```

Terraform for ECS, SQS, and RDS lives in `infra/`. `fmt` and `validate` run in CI; apply is manual.

## Layout

```
app/           FastAPI, WebSocket connection manager, REST control plane
orchestrator/  graph/state machine, node definitions, checkpointing
workers/       SQS consumer running the agent loop
events/        Redis pub/sub fan-out, sequencing, replay-on-reconnect
db/            PostgreSQL schema, migrations, run + step models
infra/         Terraform: ECS, SQS, RDS, IAM
bench/         connection load generator
docs/STUDY.md  notes from khoj and langgraph
```

## Status

Scaffold. See [ROADMAP.md](ROADMAP.md) and [docs/STUDY.md](docs/STUDY.md).
