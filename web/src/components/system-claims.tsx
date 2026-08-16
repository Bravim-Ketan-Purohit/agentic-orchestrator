"use client";

/**
 * What this project proves — maps resume claims to implementation evidence.
 */
export function SystemClaims() {
  return (
    <div className="space-y-6">
      <div className="bg-muted rounded p-4">
        <h2 className="text-lg font-bold">The Resume Claim</h2>
        <blockquote className="mt-2 pl-4 border-l-2 border-primary text-sm text-muted-foreground italic">
          "Long-running agent workflows: SQS-buffered jobs, state in PostgreSQL, partial reasoning
          streamed over WebSockets, stack provisioned as Terraform IaC. Sustained [N] concurrent
          streaming sessions without dropped connections in load tests."
        </blockquote>
      </div>

      <div className="space-y-3">
        <h3 className="font-bold">How each claim is backed</h3>

        <ClaimRow
          claim="SQS-buffered jobs"
          evidence="Standard queue + DLQ (maxReceiveCount=3). Message body is an envelope {run_id, attempt} — never the payload. Visibility-timeout heartbeat extends every 30s while work is in progress. Long polling with WaitTimeSeconds=20."
          files={["orchestrator/worker/consumer.py", "infra/sqs.tf"]}
        />

        <ClaimRow
          claim="State in PostgreSQL"
          evidence="Runs, steps, checkpoints, and events all in Postgres. Every step commit is ONE transaction covering all four. Checkpoint = full serialized workflow state as JSONB. A resumed worker loads it and continues."
          files={["orchestrator/state/manager.py", "orchestrator/db/models.py", "migrations/versions/001_initial_schema.py"]}
        />

        <ClaimRow
          claim="Partial reasoning streamed over WebSockets"
          evidence="Token-by-token, thought, tool_call, tool_result events stream live. Replay from last_seq on reconnect. Subscribe FIRST, buffer, replay, flush (discard ≤ cursor), then go live — no gaps in the handoff."
          files={["orchestrator/stream/handler.py", "orchestrator/stream/connection.py"]}
        />

        <ClaimRow
          claim="Long-running / resumable"
          evidence="Kill-at-every-step-boundary test parameterized over all 5 steps. Each test: kill worker, start new worker, load checkpoint, resume, verify all steps succeed and outputs match an uninterrupted run."
          files={["tests/test_resume.py", "orchestrator/worker/executor.py"]}
        />

        <ClaimRow
          claim="Terraform IaC"
          evidence="VPC, SQS+DLQ, RDS, ECS Fargate (API behind ALB + worker with autoscaling on queue depth), IAM roles scoped per service, SNS topic, CloudWatch. terraform fmt + validate in CI."
          files={["infra/vpc.tf", "infra/ecs.tf", "infra/alb.tf", "infra/sqs.tf", "infra/rds.tf", "infra/iam.tf"]}
        />

        <ClaimRow
          claim="Without dropped connections"
          evidence={`Every event carries a per-run gap-free sequence number. The client SDK asserts strict +1 continuity and THROWS on a gap. The load harness verifies 0 gaps across all sessions. Definition: a session is "dropped" if the client observes a gap that is never filled by replay.`}
          files={["orchestrator/events/store.py", "sdk/src/stream.ts", "bench/wsload.py"]}
        />

        <ClaimRow
          claim="No dual-write bug on completion"
          evidence="Transactional outbox: the outbox row is written in the SAME transaction as the terminal state. A relay publishes only committed rows. Test proves a rolled-back transaction publishes nothing."
          files={["orchestrator/outbox/writer.py", "orchestrator/outbox/relay.py", "tests/test_outbox.py"]}
        />

        <ClaimRow
          claim="Typed client SDK"
          evidence="TypeScript SDK with reconnect-with-replay, jittered backoff, GapError thrown on unfillable gap. Event types generated from server schemas (never hand-maintained). Works in Node 22 and browser."
          files={["sdk/src/client.ts", "sdk/src/stream.ts", "sdk/src/events.ts", "sdk/scripts/generate-types.mjs"]}
        />

        <ClaimRow
          claim="Cross-instance fan-out"
          evidence="Two API instances (:7601, :7605) both LISTEN on the same Postgres channel. Worker writes events + pg_notify. Both instances forward to their connected clients. No Redis — one mechanism for fan-out, durability, and replay."
          files={["orchestrator/events/listener.py", "docker-compose.dev.yml"]}
        />
      </div>

      {/* What's deliberately NOT here */}
      <div className="bg-muted rounded p-4">
        <h3 className="font-bold text-sm mb-2">Deliberate constraints (engineering judgment)</h3>
        <ul className="text-xs text-muted-foreground space-y-1.5">
          <li><strong className="text-foreground">No Redis.</strong> The claim is about not dropping connections. Every extra moving part is another thing that can drop one. Postgres LISTEN/NOTIFY handles fan-out with fewer failure modes.</li>
          <li><strong className="text-foreground">No Kubernetes.</strong> The resume says ECS + SQS + Terraform. K8s solves a different problem at a different scale point.</li>
          <li><strong className="text-foreground">No agent framework.</strong> This isn't LangChain. Workflows are declared in plain Python. The orchestration and persistence is the engineering, not the prompting.</li>
          <li><strong className="text-foreground">Telemetry OFF for the headline run.</strong> At target concurrency, tracing every event is more telemetry than payload. The overhead is measured and reported separately.</li>
        </ul>
      </div>
    </div>
  );
}

function ClaimRow({ claim, evidence, files }: { claim: string; evidence: string; files: string[] }) {
  return (
    <div className="border border-border rounded p-4">
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1">
          <h4 className="text-sm font-bold text-primary">{claim}</h4>
          <p className="text-xs text-muted-foreground mt-1 leading-relaxed">{evidence}</p>
        </div>
      </div>
      <div className="flex flex-wrap gap-1.5 mt-2">
        {files.map((f) => (
          <code key={f} className="text-[10px] px-1.5 py-0.5 bg-background rounded border border-border text-muted-foreground">
            {f}
          </code>
        ))}
      </div>
    </div>
  );
}
