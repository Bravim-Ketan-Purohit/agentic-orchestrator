/**
 * OrchestratorClient: typed HTTP + WebSocket client.
 *
 * Usage:
 *   const client = new OrchestratorClient({ baseUrl: "http://localhost:7601" });
 *   const run = await client.runs.create({ workflow: "research", input: { question: "..." } });
 *   for await (const ev of client.runs.stream(run.id)) { ... }
 */

import type { StreamEvent } from "./events";
import { RunStream } from "./stream";
import type {
  CreateRunInput,
  OrchestratorConfig,
  Run,
  RunDetail,
  StreamOptions,
  Workflow,
} from "./types";

export class OrchestratorClient {
  private readonly baseUrl: string;
  private readonly wsUrl: string;
  private readonly origin: string;
  private readonly maxReconnectAttempts: number;
  private readonly reconnectBaseDelay: number;

  public readonly runs: RunsAPI;

  constructor(config: OrchestratorConfig) {
    this.baseUrl = config.baseUrl.replace(/\/$/, "");
    this.wsUrl =
      config.wsUrl ?? config.baseUrl.replace(/^http/, "ws").replace(/\/$/, "");
    this.origin = config.origin ?? "http://localhost:7600";
    this.maxReconnectAttempts = config.maxReconnectAttempts ?? 10;
    this.reconnectBaseDelay = config.reconnectBaseDelay ?? 1000;

    this.runs = new RunsAPI(this);
  }

  /** Make an HTTP request to the API. */
  async fetch<T>(path: string, options?: RequestInit): Promise<T> {
    const url = `${this.baseUrl}${path}`;
    const resp = await fetch(url, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...options?.headers,
      },
    });

    if (!resp.ok) {
      const body = await resp.text();
      throw new Error(`HTTP ${resp.status}: ${body}`);
    }

    return resp.json() as Promise<T>;
  }

  /** Create a WebSocket event stream for a run. */
  createStream(runId: string, options?: StreamOptions): RunStream {
    return new RunStream({
      runId,
      wsUrl: this.wsUrl,
      origin: this.origin,
      resumeFrom: options?.resumeFrom,
      maxReconnectAttempts: this.maxReconnectAttempts,
      reconnectBaseDelay: this.reconnectBaseDelay,
      signal: options?.signal,
    });
  }
}

class RunsAPI {
  constructor(private readonly client: OrchestratorClient) {}

  /** Create a new run. Returns immediately with 202. */
  async create(input: CreateRunInput): Promise<Run> {
    return this.client.fetch<Run>("/v1/runs", {
      method: "POST",
      body: JSON.stringify(input),
    });
  }

  /** Get run details including steps and latest checkpoint. */
  async get(runId: string): Promise<RunDetail> {
    return this.client.fetch<RunDetail>(`/v1/runs/${runId}`);
  }

  /** Request cooperative cancellation of a run. */
  async cancel(runId: string): Promise<{ status: string; run_id: string }> {
    return this.client.fetch(`/v1/runs/${runId}/cancel`, { method: "POST" });
  }

  /** Stream events for a run with automatic reconnect and gap assertion. */
  stream(runId: string, options?: StreamOptions): AsyncIterable<StreamEvent> {
    return this.client.createStream(runId, options);
  }
}
