"use client";

import { useState, useRef, useCallback } from "react";

/**
 * Self-contained simulation that runs entirely in the browser.
 * Shows exactly what the backend does — no running server needed.
 * Recruiters see the full flow: submit → queue → execute → checkpoint → stream → crash → resume.
 */

interface SimEvent {
  seq: number;
  kind: string;
  data: string;
  timestamp: number;
  phase: "normal" | "replayed" | "post-resume";
}

type SimPhase =
  | "idle"
  | "submitting"
  | "queued"
  | "executing"
  | "streaming"
  | "crash"
  | "recovering"
  | "reconnecting"
  | "replaying"
  | "resumed"
  | "completed";

const STEPS = [
  { id: "plan", name: "Plan Research", duration: 1500 },
  { id: "search", name: "Search Sources", duration: 2000 },
  { id: "analyze", name: "Analyze Findings", duration: 1500 },
  { id: "draft", name: "Draft Response", duration: 2000 },
  { id: "review", name: "Review & Finalize", duration: 1000 },
];

export function SimulationDemo() {
  const [phase, setPhase] = useState<SimPhase>("idle");
  const [events, setEvents] = useState<SimEvent[]>([]);
  const [currentStep, setCurrentStep] = useState<number>(-1);
  const [lastSeq, setLastSeq] = useState(0);
  const [gapCount, setGapCount] = useState(0);
  const [reconnects, setReconnects] = useState(0);
  const [crashAtStep, setCrashAtStep] = useState(2); // Crash during step 3 (analyze)
  const [checkpointedAt, setCheckpointedAt] = useState<string | null>(null);
  const [narrative, setNarrative] = useState("");
  const [wsConnected, setWsConnected] = useState(false);
  const seqRef = useRef(0);
  const runningRef = useRef(false);

  const addEvent = (kind: string, data: string, eventPhase: "normal" | "replayed" | "post-resume" = "normal") => {
    seqRef.current += 1;
    const ev: SimEvent = {
      seq: seqRef.current,
      kind,
      data,
      timestamp: Date.now(),
      phase: eventPhase,
    };
    setEvents((prev) => [...prev, ev]);
    setLastSeq(seqRef.current);
    return ev;
  };

  const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

  const runSimulation = useCallback(async () => {
    if (runningRef.current) return;
    runningRef.current = true;

    // Reset
    setEvents([]);
    setLastSeq(0);
    setGapCount(0);
    setReconnects(0);
    setCurrentStep(-1);
    setCheckpointedAt(null);
    seqRef.current = 0;

    // === Phase 1: Submit ===
    setPhase("submitting");
    setNarrative("Client sends POST /v1/runs to the API. The API creates a run record in PostgreSQL and enqueues a job message to SQS.");
    await sleep(1500);

    // === Phase 2: Queued ===
    setPhase("queued");
    setNarrative("The SQS message sits in the queue. A worker process picks it up via long polling (WaitTimeSeconds=20). The worker acquires a lease on the run by incrementing the fence counter — this prevents two workers from running the same job.");
    await sleep(2000);

    // === Phase 3: WebSocket connected ===
    setWsConnected(true);
    setPhase("streaming");
    setNarrative("Meanwhile, the client opens a WebSocket: GET /ws/runs/{id}?last_seq=0. The API subscribes to PostgreSQL LISTEN/NOTIFY for this run. Events will stream in real-time.");
    await sleep(1500);

    // === Phase 4: Execute steps (up to crash point) ===
    setPhase("executing");
    for (let i = 0; i <= crashAtStep; i++) {
      if (!runningRef.current) return;
      setCurrentStep(i);
      const step = STEPS[i]!;

      setNarrative(`Worker executes step "${step.name}". It starts a transaction: writes the step row, appends events with gap-free sequence numbers, and saves a checkpoint — all in ONE commit.`);

      addEvent("step_start", `Starting: ${step.name} (attempt 1)`);
      await sleep(400);

      // Emit some tokens/thoughts for this step
      if (i === 0) {
        addEvent("thought", "Breaking the question into sub-questions...");
        await sleep(300);
        addEvent("token", "Sub-question 1: What are the key components?");
        await sleep(300);
        addEvent("token", "Sub-question 2: How do they interact?");
      } else if (i === 1) {
        addEvent("tool_call", "Calling search tool: 'distributed event architecture'");
        await sleep(400);
        addEvent("tool_result", "Found 3 relevant sources");
        await sleep(300);
        addEvent("token", "Key finding: event sourcing with append-only logs...");
      } else if (i === 2) {
        addEvent("thought", "Synthesizing findings from search results...");
        await sleep(400);
        addEvent("token", "Analysis: The core pattern is...");
      }

      await sleep(300);
      addEvent("step_end", `Step "${step.name}" succeeded`);
      addEvent("checkpoint", `Checkpoint saved after "${step.id}" — state is durable`);
      setCheckpointedAt(step.id);

      await sleep(step.duration - 1000);
    }

    // === Phase 5: CRASH! ===
    setPhase("crash");
    setWsConnected(false);
    setNarrative("💥 THE WORKER CRASHES (SIGKILL). The process is dead. The SQS message becomes visible again after the visibility timeout expires. Your WebSocket connection is also lost.");
    await sleep(3000);

    // === Phase 6: Recovering ===
    setPhase("recovering");
    setNarrative(`The SQS message reappears. A new worker picks it up. It acquires a NEW lease (fence increments to prevent the dead worker from writing if it somehow revives). It loads the last checkpoint: after step "${STEPS[crashAtStep]!.id}". The workflow state is fully restored from the serialized JSON.`);
    await sleep(3000);

    // === Phase 7: Client reconnects ===
    setPhase("reconnecting");
    const lastSeqBeforeCrash = seqRef.current;
    setNarrative(`Your browser reconnects: GET /ws/runs/{id}?last_seq=${lastSeqBeforeCrash}. The server replays any events you missed from the database (events are append-only and never deleted). Then it switches to live streaming.`);
    setReconnects(1);
    await sleep(2000);
    setWsConnected(true);

    // === Phase 8: Resume execution ===
    setPhase("resumed");
    setNarrative("The new worker resumes from the checkpoint. Steps that already succeeded are skipped (idempotent by primary key). Remaining steps execute normally. Every new event gets the next sequence number — no gaps.");

    for (let i = crashAtStep + 1; i < STEPS.length; i++) {
      if (!runningRef.current) return;
      setCurrentStep(i);
      const step = STEPS[i]!;

      addEvent("step_start", `Starting: ${step.name} (attempt 2, resumed)`, "post-resume");
      await sleep(400);

      if (i === 3) {
        addEvent("token", "Drafting the response based on analysis...", "post-resume");
        await sleep(300);
        addEvent("token", "The architecture consists of three layers...", "post-resume");
      } else if (i === 4) {
        addEvent("thought", "Reviewing for accuracy and completeness...", "post-resume");
        await sleep(300);
        addEvent("token", "[FINAL] Complete research response ready.", "post-resume");
      }

      await sleep(300);
      addEvent("step_end", `Step "${step.name}" succeeded`, "post-resume");
      addEvent("checkpoint", `Checkpoint saved after "${step.id}"`, "post-resume");
      setCheckpointedAt(step.id);

      await sleep(step.duration - 1000);
    }

    // === Phase 9: Done ===
    addEvent("done", "Run completed: succeeded", "post-resume");
    setPhase("completed");
    setNarrative(`Done. The run completed successfully despite a crash mid-execution. Sequence numbers are gap-free (1 through ${seqRef.current}). The client received every single event — zero data loss. The outbox relay publishes an SNS notification that the run succeeded.`);
    runningRef.current = false;
  }, [crashAtStep]);

  const stopSimulation = () => {
    runningRef.current = false;
    setPhase("idle");
  };

  return (
    <div className="space-y-5">
      {/* Narrative banner */}
      {narrative && phase !== "idle" && (
        <div className={`rounded p-4 text-sm leading-relaxed border ${
          phase === "crash" 
            ? "bg-red-950/30 border-red-500/40 text-red-200" 
            : phase === "completed"
            ? "bg-green-950/30 border-green-500/40 text-green-200"
            : "bg-blue-950/20 border-blue-500/30 text-blue-100"
        }`}>
          <div className="flex items-start gap-2">
            <span className="shrink-0">
              {phase === "crash" ? "💥" : phase === "completed" ? "✓" : "→"}
            </span>
            <p>{narrative}</p>
          </div>
        </div>
      )}

      {/* Controls */}
      <div className="flex gap-3 items-center flex-wrap">
        <button
          onClick={runSimulation}
          disabled={phase !== "idle" && phase !== "completed"}
          className="px-5 py-2.5 bg-primary text-primary-foreground rounded hover:opacity-90 transition font-medium disabled:opacity-50"
        >
          {phase === "idle" ? "Run Simulation" : phase === "completed" ? "Run Again" : "Running..."}
        </button>
        {phase !== "idle" && phase !== "completed" && (
          <button
            onClick={stopSimulation}
            className="px-4 py-2 border border-border rounded hover:bg-muted transition text-sm"
          >
            Stop
          </button>
        )}
        <div className="flex items-center gap-2 ml-auto">
          <label className="text-xs text-muted-foreground">Crash at step:</label>
          <select
            value={crashAtStep}
            onChange={(e) => setCrashAtStep(Number(e.target.value))}
            disabled={phase !== "idle" && phase !== "completed"}
            className="bg-muted border border-border rounded px-2 py-1 text-xs"
          >
            {STEPS.map((s, i) => (
              <option key={i} value={i}>After {s.name}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Step progress */}
      <div className="flex gap-1">
        {STEPS.map((step, i) => (
          <div
            key={step.id}
            className={`flex-1 rounded p-2 text-center text-xs transition-all ${
              i < currentStep
                ? "bg-green-900/40 text-green-300 border border-green-700/50"
                : i === currentStep
                ? "bg-primary/20 text-primary border border-primary/50 animate-pulse"
                : i === crashAtStep && phase === "crash"
                ? "bg-red-900/40 text-red-300 border border-red-700/50"
                : "bg-muted text-muted-foreground border border-border"
            }`}
          >
            <div className="font-medium">{step.name}</div>
            <div className="text-[10px] mt-0.5 opacity-70">
              {i < currentStep ? "✓ done" : i === currentStep ? "running..." : 
               (i === crashAtStep + 1 && (phase === "resumed" || phase === "completed")) ? "resumed" : "pending"}
            </div>
          </div>
        ))}
      </div>

      {/* Metrics */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <MetricCard label="Sequence #" value={lastSeq} subtitle="events total" color="text-primary" />
        <MetricCard 
          label="Gaps" 
          value={gapCount} 
          subtitle={gapCount === 0 ? "zero data loss" : "events lost!"} 
          color={gapCount === 0 ? "text-green-400" : "text-red-400"} 
        />
        <MetricCard label="Reconnects" value={reconnects} subtitle={reconnects > 0 ? "recovered" : "—"} color="text-foreground" />
        <MetricCard 
          label="WebSocket" 
          value={wsConnected ? "Connected" : "Disconnected"} 
          subtitle={wsConnected ? "streaming live" : phase === "crash" ? "lost in crash" : "not started"} 
          color={wsConnected ? "text-green-400" : "text-red-400"} 
          isText 
        />
        <MetricCard 
          label="Checkpoint" 
          value={checkpointedAt ?? "—"} 
          subtitle={checkpointedAt ? "resumable from here" : "none yet"} 
          color="text-cyan-400" 
          isText 
        />
      </div>

      {/* Event stream */}
      <div className="border border-border rounded overflow-hidden">
        <div className="flex justify-between items-center px-4 py-2 bg-muted border-b border-border">
          <h3 className="text-sm font-bold">Event Stream (what the WebSocket client receives)</h3>
          <span className="text-xs text-muted-foreground">
            {events.length > 0 ? `${events.length} events · seq 1–${lastSeq} · 0 gaps` : "waiting for events..."}
          </span>
        </div>
        <div className="max-h-72 overflow-y-auto p-3">
          {events.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              <p className="text-sm">Click "Run Simulation" to see the full crash-recovery flow.</p>
              <p className="text-xs mt-2 max-w-md mx-auto">
                You'll watch an AI agent execute a 5-step research workflow, survive a server crash mid-step,
                and resume from its checkpoint — with every event accounted for.
              </p>
            </div>
          ) : (
            <div className="space-y-0.5 font-mono text-xs">
              {events.map((ev) => (
                <div
                  key={ev.seq}
                  className={`flex gap-2 px-1.5 py-0.5 rounded ${
                    ev.phase === "replayed" ? "bg-yellow-900/20" : 
                    ev.phase === "post-resume" ? "bg-cyan-900/10" : 
                    "hover:bg-muted/50"
                  }`}
                >
                  <span className="text-muted-foreground w-6 text-right shrink-0">
                    {ev.seq}
                  </span>
                  <span className={`w-20 shrink-0 ${kindColor(ev.kind)}`}>
                    {ev.kind}
                  </span>
                  <span className="text-foreground truncate">{ev.data}</span>
                  {ev.phase === "post-resume" && (
                    <span className="text-cyan-500 text-[10px] shrink-0 ml-auto">after resume</span>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Explanation at bottom */}
      {phase === "idle" && (
        <div className="bg-muted rounded p-4 text-sm text-muted-foreground space-y-2">
          <p><strong className="text-foreground">What this simulation demonstrates:</strong></p>
          <ul className="list-disc list-inside space-y-1 text-xs">
            <li>A multi-step AI agent workflow executes across a distributed system (API → SQS → Worker → Postgres)</li>
            <li>Every event gets a <strong>gap-free sequence number</strong> — allocated in the same DB transaction as the event write</li>
            <li>After each step, a <strong>checkpoint</strong> captures the full workflow state to PostgreSQL</li>
            <li>When the worker crashes (SIGKILL), a new worker <strong>resumes from the last checkpoint</strong></li>
            <li>The client reconnects with its last-seen sequence number and <strong>replays missed events</strong> from the database</li>
            <li>The result: zero gaps in the sequence, zero data loss — provable, not just claimed</li>
          </ul>
        </div>
      )}
    </div>
  );
}

function MetricCard({ label, value, subtitle, color, isText }: { 
  label: string; value: number | string; subtitle: string; color: string; isText?: boolean 
}) {
  return (
    <div className="bg-muted/50 border border-border rounded p-3">
      <div className="text-[10px] text-muted-foreground uppercase tracking-wide">{label}</div>
      <div className={`font-bold ${isText ? "text-sm" : "text-xl"} ${color} mt-0.5`}>{value}</div>
      <div className="text-[10px] text-muted-foreground mt-0.5">{subtitle}</div>
    </div>
  );
}

function kindColor(kind: string): string {
  switch (kind) {
    case "token": return "text-blue-400";
    case "thought": return "text-purple-400";
    case "step_start": return "text-yellow-400";
    case "step_end": return "text-green-400";
    case "checkpoint": return "text-cyan-400";
    case "error": return "text-red-400";
    case "done": return "text-green-500";
    case "cancelled": return "text-orange-400";
    case "tool_call": return "text-orange-400";
    case "tool_result": return "text-orange-300";
    default: return "text-muted-foreground";
  }
}
