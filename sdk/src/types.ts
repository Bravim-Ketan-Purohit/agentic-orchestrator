/**
 * Client configuration and API types.
 */

export interface OrchestratorConfig {
  /** Base URL of the API (e.g., "http://localhost:7601") */
  baseUrl: string;
  /** WebSocket URL (e.g., "ws://localhost:7601"). Defaults to baseUrl with ws:// scheme. */
  wsUrl?: string;
  /** Origin header for WebSocket connections */
  origin?: string;
  /** Maximum reconnect attempts before giving up */
  maxReconnectAttempts?: number;
  /** Base delay for reconnect backoff in ms */
  reconnectBaseDelay?: number;
}

export interface CreateRunInput {
  workflow: string;
  input: Record<string, unknown>;
  idempotency_key?: string;
}

export interface Run {
  id: string;
  workflow: string;
  input: Record<string, unknown>;
  state: string;
  attempt: number;
  fence: number;
  cancel_requested: boolean;
  created_at: string;
  updated_at: string;
}

export interface Step {
  run_id: string;
  step_id: string;
  state: string;
  attempt: number;
  input?: Record<string, unknown> | null;
  output?: Record<string, unknown> | null;
  error?: Record<string, unknown> | null;
  started_at?: string | null;
  finished_at?: string | null;
}

export interface RunDetail {
  run: Run;
  steps: Step[];
  latest_checkpoint_seq: number | null;
}

export interface Workflow {
  name: string;
  description: string;
  steps: Array<{ id: string; name: string; description: string }>;
}

export interface StreamOptions {
  /** Resume streaming from this sequence number */
  resumeFrom?: number;
  /** Signal to abort the connection */
  signal?: AbortSignal;
}
