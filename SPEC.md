# SPEC — Stateful Agentic Orchestrator

**Authoritative technical specification.** `ROADMAP.md` gives the order; this gives the contents. Where
they disagree, this wins. If a requirement here looks wrong, say so and stop.

---

## 1. The claim

> Long-running agent workflows: SQS-buffered jobs, state in PostgreSQL, partial reasoning streamed over
> WebSockets, stack provisioned as Terraform IaC. Sustained **[N]** concurrent streaming sessions without
> dropped connections in load tests.

Resume stack string the build must match: *FastAPI, WebSockets, AWS (ECS, SQS), PostgreSQL, Terraform*
(`Bravim_Purohit_Backend_Engineer.tex:131`).

### "Without dropped connections" needs a detector, not an assurance

You cannot claim zero loss unless the client can *detect* loss. That single requirement drives the core
design: every event a session emits carries a **monotonic per-session sequence number**, the client tracks
the highest it has seen, and the load harness asserts there are no gaps and no unexplained closes. Without
sequence numbers, "no dropped connections" means "nobody was watching."

Define it precisely and put the definition in the README:

> A session is **dropped** if the server closes it without the client having requested closure, or if the
> client observes a gap in the sequence number that is never filled by replay, or if the final event never
> arrives within the timeout. Client-initiated reconnects that successfully replay from `last_seq` are
> **not** drops — they are the recovery path working, and they are counted and reported separately.

## 2. Non-goals

- Not an agent framework. Workflows are defined in code; this orchestrates and persists them.
- No model training, no fine-tuning, no RAG. Agent steps call an LLM API and that's it.
- No multi-tenant auth beyond per-key scoping.
- No Kubernetes. ECS + SQS + Terraform, as the resume says.
- No human-in-the-loop approvals (that's the `helpdesk-agent-studio` project — don't duplicate it).

## 3. Architecture

```
 client ──HTTP POST /runs──► API (FastAPI :7601 / :7605)
                                  │
                                  ├─► Postgres :7602   runs, steps, checkpoints, events
                                  └─► SQS :7604        job envelope {run_id, attempt}
                                            │
                                  ┌─────────┴──────────┐
                              worker A             worker B        (ECS tasks)
                              receive → heartbeat visibility
                              execute step → checkpoint → append events
                                            │
                                            ▼
                              INSERT INTO events (run_id, seq, …)
                                     + pg_notify('run:<id>', seq)
                                            │
 client ──WS /ws/runs/{id}?last_seq=N──► ANY API instance
                                            │ LISTEN run:<id>  ──► read events WHERE seq > cursor
                                            ▼
                                    stream to client, in order, no gaps
```

### Cross-instance fan-out without adding a dependency

The hard problem: a client's WebSocket lands on API instance 1, while the worker executing that run is
somewhere else entirely. The events must reach the socket.

The obvious answer is Redis pub/sub. **Don't reach for it first** — the resume stack line lists Postgres
and not Redis, and Postgres already solves this:

1. Workers **append** events to an `events` table — durable, ordered, replayable.
2. Workers then `pg_notify('run:<id>', '<seq>')` as a *wake-up signal only*, never as the payload.
3. Any API instance holding a socket for that run is `LISTEN`ing; on notify it reads rows `seq > cursor`
   and forwards them.

This gets three properties from one mechanism: cross-instance fan-out, durability, and replay-on-reconnect
(the same query, with the client's `last_seq` as the cursor). Payloads never travel through NOTIFY, so the
8 kB limit is irrelevant, and a missed notification degrades to a poll rather than losing data — add a slow
poll fallback (250–500 ms) so a dropped notify can never mean a stalled stream.

Document the limits honestly in the README: `LISTEN/NOTIFY` needs a connection per listener, so at high
socket counts you multiplex many runs over few listeners (one listener per API instance on a wildcard
channel, dispatching in-process). If a measured throughput ceiling forces Redis, that is a legitimate
finding — but then the resume stack line must gain Redis, so raise it rather than silently adding it.

## 4. Data model

```sql
CREATE TYPE run_state  AS ENUM ('queued','running','waiting','succeeded','failed','cancelled');
CREATE TYPE step_state AS ENUM ('pending','running','succeeded','failed','skipped');

CREATE TABLE runs (
  id UUID PRIMARY KEY,
  workflow      TEXT NOT NULL,
  input         JSONB NOT NULL,
  state         run_state NOT NULL DEFAULT 'queued',
  attempt       INT NOT NULL DEFAULT 0,
  owner_worker  TEXT,
  lease_expires TIMESTAMPTZ,
  fence         BIGINT NOT NULL DEFAULT 0,
  idempotency_key TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX runs_idem ON runs (idempotency_key) WHERE idempotency_key IS NOT NULL;

CREATE TABLE steps (
  run_id UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  step_id TEXT NOT NULL,
  state step_state NOT NULL DEFAULT 'pending',
  attempt INT NOT NULL DEFAULT 0,
  input JSONB, output JSONB, error JSONB,
  started_at TIMESTAMPTZ, finished_at TIMESTAMPTZ,
  PRIMARY KEY (run_id, step_id)
);

-- The resume point. One row per completed step; a worker resumes from the newest.
CREATE TABLE checkpoints (
  run_id UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  seq BIGINT NOT NULL,
  after_step TEXT NOT NULL,
  state JSONB NOT NULL,          -- full serialised workflow state
  fence BIGINT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (run_id, seq)
);

-- The stream. Append-only, gap-free per run. Source of both live delivery and replay.
CREATE TABLE events (
  run_id UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  seq BIGINT NOT NULL,
  kind TEXT NOT NULL,            -- token | thought | tool_call | tool_result | step_start
                                 -- | step_end | checkpoint | error | done
  payload JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (run_id, seq)
);
```

`seq` is allocated **per run**, gap-free, inside the same transaction that writes the event —
`SELECT coalesce(max(seq),0)+1 … FOR UPDATE` on the run row, or a per-run counter column. A global sequence
will have gaps from rolled-back transactions, and gaps are indistinguishable from loss to the client. This
detail is the difference between a provable claim and an unprovable one.

Retention: events are the stream *and* the audit log, so they grow fast. Specify a policy — e.g. full
retention for 7 days, then compact `token` events while keeping structural ones — and implement it before
the load test, or the load test will be measuring disk growth.

## 5. Long-running work: the four mechanisms

### SQS buffering

- Standard queue + DLQ (`maxReceiveCount` 3–5). Message body is an envelope: `{run_id, attempt}` — never
  the workflow payload. Payloads live in Postgres; SQS has a 256 kB limit and a message body is not a
  database.
- **Visibility-timeout heartbeat.** Agent steps can run for minutes; a fixed visibility timeout either
  expires mid-work (causing duplicate execution) or is set so long that a genuine crash stalls the run.
  Instead: short visibility (~60 s) plus a background task calling `ChangeMessageVisibility` on a timer
  while work is in progress. Stop extending on completion or lease loss.
- Long polling (`WaitTimeSeconds=20`). Never a busy-poll loop.
- Deduplication is at the run level via `idempotency_key`, not via SQS — a standard queue gives at-least-
  once delivery and duplicate receives must be *harmless*, which §5-idempotency guarantees.

### Postgres state + checkpointing

After every step: write `steps` row, `checkpoints` row, and events in **one transaction**. Either the step
is recorded as done with its state captured, or it is retried from the previous checkpoint. There is no
in-between state, by construction.

On resume: load the newest checkpoint, restore the workflow state, continue from `after_step`. A resumed run
must produce the same downstream behaviour as an uninterrupted one — assert this in a test that kills a
worker at every step boundary in turn and compares final outputs.

### Idempotent, fenced step execution

`runs.fence` increments on each lease acquisition. Every write a worker makes is conditional on holding the
current fence. A worker that stalls past its lease, gets superseded, then wakes up cannot write — the fence
check rejects it. Same pattern as the sibling task-queue project, and it is what makes duplicate SQS
delivery safe.

Step-level idempotency: `(run_id, step_id)` is the primary key, and a step whose state is already
`succeeded` is skipped on replay rather than re-executed. LLM calls specifically must be replay-safe —
cache the completion against `(run_id, step_id, attempt)` so a resume doesn't re-bill and doesn't produce a
divergent answer.

### WebSocket streaming

- `GET /ws/runs/{run_id}?last_seq=N` — on connect, replay `seq > N` from the table, then go live. The
  handoff from replay to live must not drop or duplicate: subscribe **first**, buffer, then replay, then
  flush the buffer discarding anything at or below the last replayed seq.
- Heartbeat ping/pong (~20 s) with idle-timeout close, so dead sockets don't accumulate.
- Per-connection send queue with a bounded buffer. A slow consumer must not apply backpressure to the
  worker — bound the queue, and on overflow close the socket with a code telling the client to reconnect
  with `last_seq`. Buffering without a bound is how a single slow client OOMs the instance.
- Auth on the handshake; a token in the query string is acceptable only over TLS and must be short-lived.
- `Origin` validation. WebSockets are not covered by CORS, and this is the standard oversight.

## 6. API

```
POST   /v1/runs            {workflow, input, idempotency_key?} → 202 {run_id, state}
GET    /v1/runs/{id}                → run + steps + latest checkpoint seq
GET    /v1/runs/{id}/events?after=  → paged event history (the non-WS read path)
POST   /v1/runs/{id}/cancel         → cooperative cancel, checkpointed
WS     /ws/runs/{id}?last_seq=      → live stream with replay
GET    /v1/workflows                → registered workflows + schemas
GET    /healthz  /readyz  /metrics
```

`/readyz` must fail when Postgres or SQS is unreachable — ECS uses it to pull the task from the load
balancer, and a ready instance that can't serve is worse than one marked unhealthy.

## 7. Console (`web/`)

Next.js + TypeScript + Tailwind + shadcn/ui.

1. **Start a run**, watch tokens and reasoning arrive live.
2. **Timeline.** Steps with durations, checkpoint markers, tool calls expandable.
3. **Resilience demo** — the money screen. Buttons to kill the worker mid-run and to force-close the
   socket. The viewer then *watches* the run resume from its last checkpoint and the stream replay fill the
   gap, with the sequence counter visible throughout. This is the claim, made visible.
4. **Load panel.** Live connection count, delivery-lag p95, gap count, reconnect count during a load run.

M6 work. No orchestrator code imports from `web/`.

## 8. Load-test protocol

`bench/wsload`: asyncio client fleet. Flags `--sessions`, `--ramp`, `--hold`, `--tokens-per-run`,
`--reconnect-rate`.

Each simulated client: opens a socket, tracks `last_seq`, asserts strict monotonic +1, records delivery lag
per event, and reconnects with `last_seq` when instructed. The harness reports **sessions sustained, gap
count (must be 0), server-initiated closes, reconnect success rate, delivery-lag p50/p95/p99, and per-
connection memory**.

Rules that keep `[N]` honest:

1. **State the hardware and the topology.** "[N] concurrent sessions" on a laptop and on two ECS tasks are
   different claims. The resume says ECS — so the headline run belongs on ECS, Terraform'd up and destroyed
   the same day.
2. **Raise `ulimit -n` and say so.** The default macOS descriptor limit will cap you long before the code
   does, and a limit-bound number describes the limit, not the system.
3. **Watch out for the harness being the bottleneck.** If the load generator's own event loop saturates,
   you're measuring the client. Check CPU on the generator; if it's pegged, split across processes or hosts
   before reporting the number.
4. **Hold long enough to matter.** Ramp to N, hold ≥ 10 minutes, and report the hold duration. Connection
   counts that survive 30 seconds prove nothing about leaks or slow-consumer accumulation.
5. **Include a reconnect fraction** (e.g. 5 % of clients dropping and resuming). Zero gaps *with* churn is
   a much stronger result than zero gaps in a static run.

Rough expectation for calibration, not a target to reverse-engineer: idle asyncio WebSockets cost on the
order of tens of KB each, so a few thousand per instance is realistic and 100 k on one task is not. Let the
measurement pick the number.

## 9. Terraform requirements

`infra/` must actually run — it's a resume claim by itself:

- VPC + subnets, SQS queue + DLQ with redrive policy, RDS Postgres (or a container for cheap runs), ECS
  cluster with a Fargate service for the API behind an ALB (WebSocket-capable, idle timeout raised) and a
  service for workers, IAM task roles scoped per service (workers get SQS receive/delete; API gets send),
  CloudWatch log groups, autoscaling on queue depth.
- ALB idle timeout **must** exceed the WS heartbeat interval, or the load balancer becomes the source of
  the dropped connections you're claiming not to have. Set both explicitly and note the relationship.
- `terraform fmt` + `validate` in CI; `plan` needs credentials and stays out of CI.
- A `make load-cloud` that applies, runs the load test, pulls results, and destroys — destroying on failure
  paths too. Include a cost estimate in the README.

## 10. Milestone acceptance criteria

- **M1 Core.** Run submission → SQS → worker → steps in Postgres → terminal state. Local SQS via ElasticMQ
  or LocalStack. Migrations.
- **M2 Streaming.** Events table with gap-free per-run seq; `LISTEN/NOTIFY` fan-out with poll fallback; WS
  endpoint with replay from `last_seq`; bounded per-connection queue; two API instances (:7601, :7605)
  proving cross-instance delivery.
- **M3 Durability.** Checkpoint per step; visibility heartbeat; fencing; resume-after-`SIGKILL` test that
  kills at every step boundary and compares outputs; DLQ on poison messages.
- **M4 Correctness under churn.** Reconnect replay produces no gaps and no duplicates; cancel is
  cooperative and checkpointed; slow-consumer overflow closes cleanly instead of growing memory.
- **M5 Load.** `bench/wsload` reports 0 gaps at target N with churn, ≥ 10-minute hold, on ECS; results
  committed. **README Benchmarks table filled.**
- **M6 Presentable.** Console with the resilience demo; Terraform applies and destroys; README diagram
  accurate; CI green.

## 11. Honest-claims register

| Claim | Status | Backed by |
| --- | --- | --- |
| SQS-buffered jobs | ☐ | queue + DLQ + visibility heartbeat + long polling |
| state in PostgreSQL | ☐ | runs/steps/checkpoints/events schema, transactional step commit |
| partial reasoning streamed over WebSockets | ☐ | token/thought events live, replayable |
| long-running / resumable | ☐ | kill-at-every-step-boundary test, outputs match |
| Terraform IaC | ☐ | `apply` → load test → `destroy` executed on AWS |
| sustained `[N]` concurrent sessions | ☐ | `bench/results/…json`, hardware + topology + hold time stated |
| **without dropped connections** | ☐ | 0 sequence gaps under churn, with the §1 definition published |

Any unchecked row ⇒ `Bravim_Purohit_Backend_Engineer.tex:134` stays commented and `[N]` stays bracketed.
