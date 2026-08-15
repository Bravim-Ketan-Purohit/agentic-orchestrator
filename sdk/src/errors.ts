/**
 * Errors thrown by the SDK.
 */

/**
 * Thrown when a gap is detected in the event sequence that cannot be filled.
 * A client that silently continues past a gap makes the headline claim unverifiable.
 */
export class GapError extends Error {
  public readonly expected: number;
  public readonly received: number;
  public readonly runId: string;

  constructor(runId: string, expected: number, received: number) {
    super(
      `Gap detected in run ${runId}: expected seq ${expected}, received ${received}. ` +
        `This gap cannot be filled — the stream is unreliable.`
    );
    this.name = "GapError";
    this.runId = runId;
    this.expected = expected;
    this.received = received;
  }
}

export class ConnectionError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ConnectionError";
  }
}
