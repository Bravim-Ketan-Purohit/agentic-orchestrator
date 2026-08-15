/**
 * RunStream: WebSocket-based event stream with reconnect-and-replay.
 *
 * Key behaviors:
 * - Tracks last_seq internally
 * - Automatic reconnect with jittered backoff
 * - ASSERTS gap-free delivery and throws GapError on an unfillable gap
 * - Exposes a resumeFrom token the caller can persist
 * - Works in Node 22 and the browser
 */

import type { StreamEvent } from "./events";
import { ConnectionError, GapError } from "./errors";

export interface RunStreamOptions {
  runId: string;
  wsUrl: string;
  origin?: string;
  resumeFrom?: number;
  maxReconnectAttempts?: number;
  reconnectBaseDelay?: number;
  signal?: AbortSignal;
}

export class RunStream implements AsyncIterable<StreamEvent> {
  private readonly runId: string;
  private readonly wsUrl: string;
  private readonly origin: string;
  private readonly maxReconnectAttempts: number;
  private readonly reconnectBaseDelay: number;
  private readonly signal?: AbortSignal;
  private lastSeq: number;
  private reconnectCount = 0;
  private closed = false;

  constructor(options: RunStreamOptions) {
    this.runId = options.runId;
    this.wsUrl = options.wsUrl;
    this.origin = options.origin ?? "http://localhost:7600";
    this.lastSeq = options.resumeFrom ?? 0;
    this.maxReconnectAttempts = options.maxReconnectAttempts ?? 10;
    this.reconnectBaseDelay = options.reconnectBaseDelay ?? 1000;
    this.signal = options.signal;
  }

  /** The last successfully received sequence number. Persist this for resume. */
  get resumeToken(): number {
    return this.lastSeq;
  }

  /** Total reconnect attempts made. */
  get reconnects(): number {
    return this.reconnectCount;
  }

  /** Close the stream. */
  close(): void {
    this.closed = true;
  }

  async *[Symbol.asyncIterator](): AsyncIterator<StreamEvent> {
    let attempts = 0;

    while (!this.closed) {
      if (this.signal?.aborted) {
        return;
      }

      try {
        const url = `${this.wsUrl}/ws/runs/${this.runId}?last_seq=${this.lastSeq}`;
        const ws = await this.connect(url);

        attempts = 0; // Reset on successful connection

        try {
          for await (const event of this.receiveEvents(ws)) {
            yield event;

            // Terminal events end the stream
            if (
              event.kind === "done" ||
              event.kind === "cancelled" ||
              event.kind === "error"
            ) {
              this.closed = true;
              return;
            }
          }
        } catch (e) {
          if (this.closed || this.signal?.aborted) return;
          // Connection lost — will reconnect
        }

        if (this.closed) return;

        // Reconnect with backoff
        attempts++;
        this.reconnectCount++;

        if (attempts > this.maxReconnectAttempts) {
          throw new ConnectionError(
            `Failed to reconnect after ${this.maxReconnectAttempts} attempts`
          );
        }

        const delay = this.jitteredBackoff(attempts);
        await this.sleep(delay);
      } catch (e) {
        if (e instanceof GapError || e instanceof ConnectionError) {
          throw e;
        }
        if (this.closed || this.signal?.aborted) return;

        attempts++;
        if (attempts > this.maxReconnectAttempts) {
          throw new ConnectionError(
            `Failed to reconnect after ${this.maxReconnectAttempts} attempts`
          );
        }
        const delay = this.jitteredBackoff(attempts);
        await this.sleep(delay);
      }
    }
  }

  private async connect(url: string): Promise<WebSocket> {
    return new Promise<WebSocket>((resolve, reject) => {
      let ws: WebSocket;

      // Node.js vs Browser WebSocket
      if (typeof globalThis.WebSocket !== "undefined") {
        ws = new globalThis.WebSocket(url);
      } else {
        // Node.js — use the ws package
        try {
          // Dynamic import for Node.js
          const WS = require("ws");
          ws = new WS(url, { headers: { Origin: this.origin } });
        } catch {
          reject(new ConnectionError("WebSocket not available"));
          return;
        }
      }

      const onOpen = () => {
        ws.removeEventListener("error", onError);
        resolve(ws);
      };
      const onError = (e: Event) => {
        ws.removeEventListener("open", onOpen);
        reject(new ConnectionError("WebSocket connection failed"));
      };

      ws.addEventListener("open", onOpen);
      ws.addEventListener("error", onError);
    });
  }

  private async *receiveEvents(ws: WebSocket): AsyncGenerator<StreamEvent> {
    const queue: (StreamEvent | Error | null)[] = [];
    let resolve: (() => void) | null = null;

    const onMessage = (event: MessageEvent | { data: string }) => {
      const data = typeof event === "object" && "data" in event ? event.data : event;
      try {
        const parsed = JSON.parse(typeof data === "string" ? data : String(data));

        // Handle ping
        if (parsed.type === "ping") {
          ws.send(JSON.stringify({ type: "pong" }));
          return;
        }

        // Must have a seq to be a real event
        if (typeof parsed.seq !== "number") return;

        const streamEvent = parsed as StreamEvent;

        // Gap assertion: THROW on unfillable gap
        const expected = this.lastSeq + 1;
        if (streamEvent.seq > expected) {
          queue.push(new GapError(this.runId, expected, streamEvent.seq));
        } else if (streamEvent.seq <= this.lastSeq) {
          // Duplicate — discard (replay overlap)
          return;
        }

        if (!(queue[queue.length - 1] instanceof Error)) {
          this.lastSeq = streamEvent.seq;
          queue.push(streamEvent);
        }

        resolve?.();
      } catch {
        // Ignore parse errors
      }
    };

    const onClose = () => {
      queue.push(null);
      resolve?.();
    };

    const onError = () => {
      queue.push(null);
      resolve?.();
    };

    ws.addEventListener("message", onMessage as EventListener);
    ws.addEventListener("close", onClose);
    ws.addEventListener("error", onError);

    try {
      while (true) {
        if (queue.length === 0) {
          await new Promise<void>((r) => {
            resolve = r;
          });
          resolve = null;
        }

        const item = queue.shift();
        if (item === null || item === undefined) return;
        if (item instanceof Error) throw item;
        yield item;
      }
    } finally {
      ws.removeEventListener("message", onMessage as EventListener);
      ws.removeEventListener("close", onClose);
      ws.removeEventListener("error", onError);
      try {
        ws.close();
      } catch {
        // Ignore close errors
      }
    }
  }

  private jitteredBackoff(attempt: number): number {
    const base = this.reconnectBaseDelay * Math.pow(2, attempt - 1);
    const jitter = base * 0.5 * Math.random();
    return Math.min(base + jitter, 30000);
  }

  private sleep(ms: number): Promise<void> {
    return new Promise((r) => setTimeout(r, ms));
  }
}
