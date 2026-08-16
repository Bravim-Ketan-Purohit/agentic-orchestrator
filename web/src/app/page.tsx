"use client";

import { useState } from "react";
import { BackendStatus } from "@/components/backend-status";
import { ArchitectureView } from "@/components/architecture-view";
import { SimulationDemo } from "@/components/simulation-demo";
import { LiveDemo } from "@/components/live-demo";
import { SystemClaims } from "@/components/system-claims";

type Tab = "simulation" | "live" | "architecture" | "claims";

export default function Home() {
  const [activeTab, setActiveTab] = useState<Tab>("simulation");
  const [backendConnected, setBackendConnected] = useState(false);

  return (
    <main className="container mx-auto p-6 max-w-6xl">
      <header className="mb-4">
        <h1 className="text-2xl font-bold text-primary">
          Stateful Agentic Orchestrator
        </h1>
        <p className="text-muted-foreground mt-1 text-sm leading-relaxed max-w-3xl">
          A backend system for running long-running AI agent workflows that <strong className="text-foreground">never loses data</strong> —
          even when servers crash or connections drop. SQS-buffered jobs, per-step checkpointing in PostgreSQL,
          real-time WebSocket streaming with gap-free replay.
        </p>
        <div className="flex gap-2 mt-3 flex-wrap">
          <span className="px-2 py-0.5 bg-muted text-xs rounded">FastAPI</span>
          <span className="px-2 py-0.5 bg-muted text-xs rounded">WebSockets</span>
          <span className="px-2 py-0.5 bg-muted text-xs rounded">PostgreSQL</span>
          <span className="px-2 py-0.5 bg-muted text-xs rounded">AWS SQS</span>
          <span className="px-2 py-0.5 bg-muted text-xs rounded">Terraform</span>
          <span className="px-2 py-0.5 bg-muted text-xs rounded">TypeScript SDK</span>
          <span className="px-2 py-0.5 bg-muted text-xs rounded">OpenTelemetry</span>
        </div>
      </header>

      {/* Live backend status — always visible */}
      <div className="mb-4">
        <BackendStatus onStatusChange={setBackendConnected} />
      </div>

      {/* Tab navigation */}
      <nav className="flex gap-2 mb-6 border-b border-border pb-2 flex-wrap">
        <button
          onClick={() => setActiveTab("simulation")}
          className={`px-4 py-2 rounded-t text-sm transition-colors ${
            activeTab === "simulation"
              ? "bg-primary text-primary-foreground font-medium"
              : "text-muted-foreground hover:text-foreground"
          }`}
        >
          Simulation Demo
        </button>
        <button
          onClick={() => setActiveTab("live")}
          className={`px-4 py-2 rounded-t text-sm transition-colors relative ${
            activeTab === "live"
              ? "bg-primary text-primary-foreground font-medium"
              : "text-muted-foreground hover:text-foreground"
          }`}
        >
          Live Backend
          {backendConnected && (
            <span className="absolute -top-1 -right-1 w-2 h-2 bg-green-400 rounded-full" />
          )}
        </button>
        <button
          onClick={() => setActiveTab("architecture")}
          className={`px-4 py-2 rounded-t text-sm transition-colors ${
            activeTab === "architecture"
              ? "bg-primary text-primary-foreground font-medium"
              : "text-muted-foreground hover:text-foreground"
          }`}
        >
          Architecture
        </button>
        <button
          onClick={() => setActiveTab("claims")}
          className={`px-4 py-2 rounded-t text-sm transition-colors ${
            activeTab === "claims"
              ? "bg-primary text-primary-foreground font-medium"
              : "text-muted-foreground hover:text-foreground"
          }`}
        >
          What This Proves
        </button>
      </nav>

      {activeTab === "simulation" && <SimulationDemo />}
      {activeTab === "live" && (
        backendConnected ? (
          <LiveDemo />
        ) : (
          <div className="text-center py-12 space-y-3">
            <p className="text-muted-foreground">Backend is not connected.</p>
            <p className="text-xs text-muted-foreground max-w-md mx-auto">
              The Live Backend tab connects to the real FastAPI server, PostgreSQL, and SQS worker to demonstrate
              that the system actually works end-to-end — not just a UI simulation.
            </p>
            <div className="bg-muted rounded p-4 text-xs text-muted-foreground max-w-lg mx-auto text-left space-y-1">
              <p className="font-medium text-foreground">To start the backend locally:</p>
              <code className="block mt-1">docker compose -f docker-compose.dev.yml up -d postgres elasticmq</code>
              <code className="block">alembic upgrade head</code>
              <code className="block">uvicorn orchestrator.api.app:app --port 7601 --reload</code>
              <code className="block">python -m orchestrator.worker --concurrency 4</code>
            </div>
            <p className="text-xs text-muted-foreground">
              Meanwhile, try the <button onClick={() => setActiveTab("simulation")} className="text-primary underline">Simulation Demo</button> to see the flow.
            </p>
          </div>
        )
      )}
      {activeTab === "architecture" && <ArchitectureView />}
      {activeTab === "claims" && <SystemClaims />}

      <footer className="mt-8 pt-4 border-t border-border text-xs text-muted-foreground">
        <a href="https://github.com/Bravim-Ketan-Purohit/agentic-orchestrator" className="hover:text-primary transition">
          github.com/Bravim-Ketan-Purohit/agentic-orchestrator
        </a>
        {" · "}
        Stack: FastAPI · WebSockets · AWS (ECS, SQS) · PostgreSQL · Terraform
      </footer>
    </main>
  );
}
