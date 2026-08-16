"use client";

import { useState, useEffect, useRef } from "react";

const API_URL = "http://localhost:7601";

interface HealthStatus {
  api: boolean;
  postgres: boolean;
  sqs: boolean;
  worker: boolean;
}

interface Props {
  onStatusChange?: (connected: boolean) => void;
}

/**
 * Shows live backend connectivity status.
 * Pings the API every 3 seconds. When all services are green,
 * the recruiter knows this is real infrastructure, not just UI.
 */
export function BackendStatus({ onStatusChange }: Props) {
  const [status, setStatus] = useState<HealthStatus>({
    api: false,
    postgres: false,
    sqs: false,
    worker: false,
  });
  const [latency, setLatency] = useState<number | null>(null);
  const intervalRef = useRef<NodeJS.Timeout | null>(null);

  useEffect(() => {
    checkHealth();
    intervalRef.current = setInterval(checkHealth, 3000);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, []);

  const checkHealth = async () => {
    const start = Date.now();
    try {
      const resp = await fetch(`${API_URL}/readyz`, { signal: AbortSignal.timeout(2000) });
      const data = await resp.json();
      const ms = Date.now() - start;
      setLatency(ms);

      const newStatus = {
        api: true,
        postgres: data.postgres ?? false,
        sqs: data.sqs ?? false,
        worker: true, // If API is up and healthy, worker connectivity is implied via SQS
      };
      setStatus(newStatus);
      onStatusChange?.(newStatus.api && newStatus.postgres);
    } catch {
      setLatency(null);
      setStatus({ api: false, postgres: false, sqs: false, worker: false });
      onStatusChange?.(false);
    }
  };

  const allGreen = status.api && status.postgres && status.sqs;

  return (
    <div className={`rounded p-3 border text-xs ${
      allGreen 
        ? "bg-green-950/20 border-green-500/30" 
        : status.api 
        ? "bg-yellow-950/20 border-yellow-500/30"
        : "bg-muted border-border"
    }`}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="font-medium text-foreground">Backend:</span>
          <StatusDot active={status.api} label="API" />
          <StatusDot active={status.postgres} label="PostgreSQL" />
          <StatusDot active={status.sqs} label="SQS" />
        </div>
        <div className="text-muted-foreground">
          {allGreen ? (
            <span className="text-green-400">All services connected · {latency}ms</span>
          ) : status.api ? (
            <span className="text-yellow-400">API up, some services unavailable</span>
          ) : (
            <span>Not connected — simulation mode</span>
          )}
        </div>
      </div>
    </div>
  );
}

function StatusDot({ active, label }: { active: boolean; label: string }) {
  return (
    <div className="flex items-center gap-1">
      <div className={`w-2 h-2 rounded-full ${active ? "bg-green-400" : "bg-muted-foreground/30"}`} />
      <span className={active ? "text-foreground" : "text-muted-foreground"}>{label}</span>
    </div>
  );
}
