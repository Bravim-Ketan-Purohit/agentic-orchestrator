# Load-Test Results — Stateful Agentic Orchestrator

Recorded 2026-08-17. Host: Apple M3 Pro, 11 cores, 18 GB, macOS 27.0 arm64 (all components + load harness on one machine).
`ulimit -n` 65536. Topology: 2 API instances (:7601, :7605), 2–4 workers, Postgres, ElasticMQ.

## Headline: the streaming layer is correct; throughput is the limit

| Sessions | Hold | Events | **Seq gaps** | Reconnects | Reconnect failures | Lag p50 | Lag p95 | Lag p99 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 50 | 25 s | 1 219 | **0** | 13 | 0 | 41.6 ms | 104.0 ms | 166.3 ms |
| 150 | 300 s | 5 090 | **0** | 289 | 0 | 1 260 ms | 9 716 ms | 12 850 ms |
| 500 | 40 s | 1 798 | **0** | 512 | 0 | 62 ms | 26 895 ms | 32 171 ms |
| 1000 | 300 s | 2 205 | **0** | 436 | 0 | 50 792 ms | 58 423 ms | 60 756 ms |

**Zero sequence gaps at every level, including under 5 % reconnect churn, with every
reconnect replaying cleanly from `last_seq`.** That is the claim the design exists to
support, and it holds.

**Sessions sustained** degrades above ~150: 500 requested yielded 125 sustained, 1000
yielded 65. Raising the DB pool (20+10 → 60+40) and Postgres `max_connections`
(100 → 500), and running 4 workers at concurrency 24, did **not** move it. The
bottleneck is **run execution throughput**, not the streaming layer: each session creates
a run that a worker must execute, so session capacity is bounded by how fast runs drain,
and queued runs show up as delivery lag rather than as dropped connections.

### What this supports on the resume

Defensible today: **150 concurrent streaming sessions held 5 minutes, 0 sequence gaps,
289 reconnects all replayed clean** — with delivery lag stated, because at 150 the p99 is
12.8 s and that is not a number to hide.

Not defensible: any figure above ~150, or any figure quoted without its delivery lag.

To raise it honestly, either make run execution faster, or measure a workload where many
sessions attach to fewer long-lived runs — which is what "concurrent streaming sessions"
usually means in production and would isolate the streaming layer properly.

## Two bugs found and fixed while running this

### 1. The gap-free sequence allocator never worked

`orchestrator/events/store.py` allocated `seq` with:

```sql
SELECT COALESCE(MAX(seq), 0) + 1 AS next_seq FROM events WHERE run_id = :run_id FOR UPDATE
```

Postgres rejects this: `FeatureNotSupportedError: FOR UPDATE is not allowed with
aggregate functions`. **Every run failed at its first step**, so the system had never
emitted a single event. The function's own docstring said "FOR UPDATE on the run row" —
the SQL locked an aggregate over `events` instead.

Fixed by locking the run row first, then computing the max in a second statement. The row
lock is what actually serialises allocation.

### 2. The load harness could never connect

`bench/wsload.py` passed `extra_headers=` to `websockets.connect`. That kwarg was renamed
`additional_headers` in websockets 14; the pinned version is 17.0.1, so all 100 clients
failed with `unexpected keyword argument 'extra_headers'`. Fixed.

Together these mean **no load-test result predating 2026-08-17 can be genuine** — the harness
could not open a socket and the server could not emit an event.

## Open issue

`orchestrator/state/manager.py` allocates checkpoint `seq` with `MAX(seq)+1` and **no row
lock**. It does not crash, and checkpoints are written in the same transaction as events
(which now takes the run lock), so it is likely serialised in practice — but it is not
serialised *by construction*. Worth making explicit.
