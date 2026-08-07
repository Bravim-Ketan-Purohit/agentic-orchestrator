# Roadmap — Stateful Agentic Orchestrator

Single-instance first, then deliberately break the single-instance assumptions. The multi-instance
event routing is the part that's actually hard, and it's invisible until you scale out — so scale out
early enough to find the bugs.

## M1 — Single-instance streaming

- [ ] FastAPI app, WebSocket endpoint, connection manager
- [ ] Trivial agent loop emitting step events
- [ ] Events streamed to the connected client in order
- [ ] Heartbeat / ping-pong so dead connections are detected rather than lingering

## M2 — Durable state

- [ ] PostgreSQL schema: runs, steps, checkpoints
- [ ] Serializable state dict checkpointed after every step
- [ ] Alembic migrations
- [ ] Step events persisted **with a monotonic sequence number** per run
- [ ] Restart the process mid-run → state survives

## M3 — Decouple work from connection

- [ ] SQS enqueue on run start
- [ ] Separate worker process consuming SQS and executing the agent loop
- [ ] Worker emits step events; API instance relays them to the client
- [ ] Client disconnect no longer cancels the run — the run continues server-side

## M4 — Reconnection and replay

- [ ] Client reconnects with a run ID + last-seen sequence number
- [ ] Server replays missed events from PostgreSQL, then resumes live streaming
- [ ] Test: disconnect mid-run, reconnect, verify **no gaps and no duplicates** in the sequence
- [ ] Test: reconnect after the run already finished → full history delivered

## M5 — Multi-instance

- [ ] Redis pub/sub fan-out so any API instance can serve any run's events
- [ ] Run 3 API instances behind a load balancer
- [ ] Test: client connects to instance A while the worker runs on instance C → events arrive
- [ ] Test: kill the instance holding a live connection → client reconnects and replays cleanly

## M6 — Worker resilience

- [ ] Worker dies mid-run → another worker resumes from the last checkpoint
- [ ] Step retries are idempotent — no duplicated side effects
- [ ] SQS visibility timeout tuned to the actual step duration
- [ ] Dead-letter queue for runs that fail terminally
- [ ] Backpressure: what happens when queue depth exceeds worker capacity

## M7 — Load test

- [ ] Connection load generator: N concurrent clients, each running a real agent workload
- [ ] Every client **verifies its received sequence is complete and ordered** — this is the actual
      "no dropped connections" measurement
- [ ] Ramp to find the per-instance ceiling; record ECS task count and size
- [ ] Sustain at the target for a meaningful duration, not a burst
- [ ] **Fill the Benchmarks table**

## M8 — Infrastructure

- [ ] Terraform: ECS services, SQS, RDS, ElastiCache, IAM roles, security groups
- [ ] `terraform fmt -check` + `validate` green in CI
- [ ] Metrics: connection count, queue depth, step duration, checkpoint lag

## M9 — Presentable

- [ ] README diagram matches the code
- [ ] CI green
- [ ] Flip repo public, then uncomment `Bravim_Purohit_Backend_Engineer.tex:134`

## Gate before the resume link goes live

`[N]` measured with per-client sequence verification, not socket counts · sustained duration and
instance count stated · reconnect-replay tested for gaps *and* duplicates · multi-instance routing
proven, since single-instance streaming is not the claim.
