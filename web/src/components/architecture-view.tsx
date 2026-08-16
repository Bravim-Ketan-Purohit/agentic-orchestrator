"use client";

/**
 * Architecture view — shows the system design with explanations.
 * Entirely visual, no running backend needed.
 */
export function ArchitectureView() {
  return (
    <div className="space-y-8">
      {/* System diagram */}
      <div className="bg-muted rounded p-6">
        <h2 className="text-lg font-bold mb-4">System Architecture</h2>
        <pre className="text-xs leading-relaxed text-muted-foreground overflow-x-auto">
{`
 Browser ──HTTP POST /runs──► API (FastAPI, 2+ instances on ECS)
                                  │
                                  ├─► PostgreSQL    runs, steps, checkpoints, events
                                  └─► SQS           job envelope {run_id, attempt}
                                            │
                              ┌──────────────┴─────────────┐
                          Worker A                     Worker B    (ECS Fargate)
                          receive → heartbeat visibility timeout
                          execute step → checkpoint → append events
                                            │
                                            ▼
                          INSERT INTO events (run_id, seq, kind, payload)
                          + pg_notify('run:<id>', seq)    ← signal only, no payload
                                            │
 Browser ──WS /ws/runs/{id}?last_seq=N──► ANY API instance
                                            │ LISTEN run:<id>
                                            ▼
                                  stream to client, in order, no gaps
`}
        </pre>
      </div>

      {/* Key design decisions */}
      <div className="grid md:grid-cols-2 gap-4">
        <DesignCard
          title="Why SQS, not just async tasks?"
          explanation="If the API server dies, in-memory async tasks die with it. SQS decouples submission from execution — the job survives any individual process failure. Visibility timeout heartbeats prevent duplicate execution without needing an excessively long timeout."
        />
        <DesignCard
          title="Why gap-free sequence numbers?"
          explanation={`You can't claim "zero dropped connections" unless you can detect a drop. Each event gets seq = max(seq)+1 FOR the run, allocated in the SAME transaction as the event write. A global sequence has gaps from rollbacks — per-run doesn't. The client asserts +1 continuity.`}
        />
        <DesignCard
          title="Why PostgreSQL LISTEN/NOTIFY, not Redis?"
          explanation="Events are already in Postgres. LISTEN/NOTIFY uses the same connection — no new dependency. A missed notification degrades to a 300ms poll (latency, not loss). Redis would add a moving part that could drop messages. The events table IS the durable pub/sub."
        />
        <DesignCard
          title="Why checkpoints after every step?"
          explanation="A checkpoint is a serialized snapshot of the full workflow state. On crash, a new worker loads it and resumes. Without checkpoints, a crash means re-running everything from scratch — which for LLM calls means paying twice and possibly getting different answers."
        />
        <DesignCard
          title="Why fencing (lease + fence counter)?"
          explanation="If Worker A stalls past its lease timeout, Worker B picks up the same job. When A wakes up, it might try to write. The fence counter prevents this: every write checks 'is my fence still current?' A stale worker's writes are rejected, preventing split-brain corruption."
        />
        <DesignCard
          title="Why a transactional outbox for SNS?"
          explanation="Publishing to SNS inside the database transaction is the dual-write bug: if the transaction rolls back, SNS already told the world 'succeeded'. The outbox writes an intent row in the same transaction. A separate relay publishes only committed rows. Rollback = no publish."
        />
        <DesignCard
          title="Why bounded WebSocket send queues?"
          explanation="One slow client shouldn't OOM the server. Each connection gets a queue of max 1024 events. On overflow, the server closes with code 4000 ('reconnect with last_seq'). The client reconnects and replays from the DB. Backpressure becomes latency, never memory exhaustion."
        />
        <DesignCard
          title="Why replay-then-live, not just live?"
          explanation="On reconnect: subscribe to NOTIFY first, then replay from DB where seq > last_seq, then flush buffered notifications (discarding duplicates ≤ cursor). This ordering guarantees no gaps during the handoff. Subscribe-after-replay would miss events that arrived during the replay query."
        />
      </div>

      {/* Data model */}
      <div className="bg-muted rounded p-6">
        <h2 className="text-lg font-bold mb-3">Data Model</h2>
        <div className="grid md:grid-cols-2 gap-4 text-xs">
          <div>
            <h3 className="font-bold text-sm mb-1 text-primary">runs</h3>
            <p className="text-muted-foreground mb-1">One row per workflow execution. Tracks state machine, fence, and lease.</p>
            <code className="text-[10px] text-muted-foreground">id, workflow, state, fence, attempt, owner_worker, lease_expires</code>
          </div>
          <div>
            <h3 className="font-bold text-sm mb-1 text-primary">steps</h3>
            <p className="text-muted-foreground mb-1">One row per step execution. PK (run_id, step_id) enforces idempotency.</p>
            <code className="text-[10px] text-muted-foreground">run_id, step_id, state, attempt, input, output, error</code>
          </div>
          <div>
            <h3 className="font-bold text-sm mb-1 text-primary">events</h3>
            <p className="text-muted-foreground mb-1">Append-only stream. PK (run_id, seq) is gap-free. Source of replay AND live.</p>
            <code className="text-[10px] text-muted-foreground">run_id, seq, kind, payload, created_at</code>
          </div>
          <div>
            <h3 className="font-bold text-sm mb-1 text-primary">checkpoints</h3>
            <p className="text-muted-foreground mb-1">Serialized workflow state after each step. The resume point.</p>
            <code className="text-[10px] text-muted-foreground">run_id, seq, after_step, state (JSONB), fence</code>
          </div>
        </div>
      </div>

      {/* Stack */}
      <div className="bg-muted rounded p-6">
        <h2 className="text-lg font-bold mb-3">Infrastructure (Terraform)</h2>
        <div className="grid md:grid-cols-3 gap-4 text-xs text-muted-foreground">
          <div>
            <h3 className="font-bold text-sm text-foreground">Compute</h3>
            <ul className="mt-1 space-y-0.5">
              <li>ECS Fargate — API service (2+ tasks)</li>
              <li>ECS Fargate — Worker service (auto-scaled)</li>
              <li>ALB with idle_timeout &gt; heartbeat interval</li>
            </ul>
          </div>
          <div>
            <h3 className="font-bold text-sm text-foreground">Messaging</h3>
            <ul className="mt-1 space-y-0.5">
              <li>SQS Standard + DLQ (maxReceiveCount=3)</li>
              <li>SNS topic for completion fan-out</li>
              <li>Transactional outbox relay</li>
            </ul>
          </div>
          <div>
            <h3 className="font-bold text-sm text-foreground">Data</h3>
            <ul className="mt-1 space-y-0.5">
              <li>RDS PostgreSQL 16</li>
              <li>LISTEN/NOTIFY for real-time fan-out</li>
              <li>Events table = stream + audit log</li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
}

function DesignCard({ title, explanation }: { title: string; explanation: string }) {
  return (
    <div className="border border-border rounded p-4">
      <h3 className="text-sm font-bold text-foreground mb-1">{title}</h3>
      <p className="text-xs text-muted-foreground leading-relaxed">{explanation}</p>
    </div>
  );
}
