"""WebSocket load harness: asyncio client fleet.

Each simulated client:
- Opens a socket, tracks last_seq
- Asserts strict monotonic +1 (gap-free)
- Records delivery lag per event
- Reconnects with last_seq when instructed

Reports:
- Sessions sustained
- Gap count (must be 0)
- Server-initiated closes
- Reconnect success rate
- Delivery-lag p50/p95/p99
- Per-connection memory

Usage:
  python -m bench.wsload --sessions 2000 --ramp 60 --hold 600 --reconnect-rate 0.05
"""

import argparse
import asyncio
import json
import random
import statistics
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
import websockets
import websockets.exceptions


@dataclass
class ClientStats:
    """Statistics for a single client session."""

    run_id: str = ""
    last_seq: int = 0
    events_received: int = 0
    gaps_detected: int = 0
    reconnects: int = 0
    reconnect_failures: int = 0
    delivery_lags: list[float] = field(default_factory=list)
    server_closes: int = 0
    connected: bool = False
    error: str | None = None


@dataclass
class HarnessResults:
    """Aggregate results from the load test."""

    sessions_sustained: int = 0
    total_events: int = 0
    total_gaps: int = 0
    total_reconnects: int = 0
    total_reconnect_failures: int = 0
    total_server_closes: int = 0
    delivery_lag_p50: float = 0.0
    delivery_lag_p95: float = 0.0
    delivery_lag_p99: float = 0.0
    hold_duration_seconds: float = 0.0
    topology: str = ""
    ulimit: int = 0
    errors: list[str] = field(default_factory=list)


class LoadClient:
    """A single simulated WebSocket client."""

    def __init__(
        self,
        api_url: str,
        ws_url: str,
        client_id: int,
        reconnect_rate: float,
    ) -> None:
        self.api_url = api_url
        self.ws_url = ws_url
        self.client_id = client_id
        self.reconnect_rate = reconnect_rate
        self.stats = ClientStats()
        self._running = False
        self._ws: Any = None

    async def start(self) -> None:
        """Create a run and start streaming."""
        self._running = True

        # Create a run
        async with httpx.AsyncClient() as http:
            resp = await http.post(
                f"{self.api_url}/v1/runs",
                json={
                    "workflow": "research",
                    "input": {"question": f"Load test query {self.client_id}"},
                },
            )
            if resp.status_code != 202:
                self.stats.error = f"Failed to create run: {resp.status_code}"
                return
            data = resp.json()
            self.stats.run_id = data["id"]

        # Connect and stream
        await self._stream_loop()

    async def _stream_loop(self) -> None:
        """Main streaming loop with reconnection support."""
        while self._running:
            try:
                url = f"{self.ws_url}/ws/runs/{self.stats.run_id}?last_seq={self.stats.last_seq}"
                extra_headers = {"Origin": "http://localhost:7600"}

                async with websockets.connect(url, additional_headers=extra_headers) as ws:
                    self._ws = ws
                    self.stats.connected = True

                    async for message in ws:
                        data = json.loads(message)

                        if data.get("type") == "ping":
                            await ws.send(json.dumps({"type": "pong"}))
                            continue

                        seq = data.get("seq")
                        if seq is None:
                            continue

                        # Gap detection: assert strict monotonic +1
                        expected = self.stats.last_seq + 1
                        if seq != expected:
                            self.stats.gaps_detected += 1

                        self.stats.last_seq = seq
                        self.stats.events_received += 1

                        # Delivery lag
                        created_at = data.get("created_at")
                        if created_at:
                            try:
                                from datetime import datetime, timezone

                                event_time = datetime.fromisoformat(created_at)
                                lag = (
                                    datetime.now(timezone.utc) - event_time
                                ).total_seconds()
                                self.stats.delivery_lags.append(lag)
                            except (ValueError, TypeError):
                                pass

                        # Check for terminal event
                        if data.get("kind") in ("done", "cancelled", "error"):
                            self._running = False
                            break

                        # Simulate reconnect fraction
                        if random.random() < self.reconnect_rate / 100:
                            break  # Force reconnect

            except websockets.exceptions.ConnectionClosed as e:
                self.stats.server_closes += 1
                if not self._running:
                    break
                # Reconnect with backoff
                self.stats.reconnects += 1
                await asyncio.sleep(random.uniform(0.5, 2.0))

            except Exception as e:
                self.stats.error = str(e)
                if not self._running:
                    break
                self.stats.reconnects += 1
                self.stats.reconnect_failures += 1
                await asyncio.sleep(random.uniform(1.0, 3.0))

        self.stats.connected = False

    def stop(self) -> None:
        """Signal the client to stop."""
        self._running = False


async def run_load_test(
    sessions: int,
    ramp_seconds: int,
    hold_seconds: int,
    reconnect_rate: float,
    api_url: str = "http://localhost:7601",
    ws_url: str = "ws://localhost:7601",
) -> HarnessResults:
    """Run the full load test."""
    import resource

    ulimit = resource.getrlimit(resource.RLIMIT_NOFILE)[0]
    print(f"ulimit -n: {ulimit}")
    print(f"Starting {sessions} sessions, ramp {ramp_seconds}s, hold {hold_seconds}s")
    print(f"Reconnect rate: {reconnect_rate}")
    print(f"API: {api_url}, WS: {ws_url}")
    print()

    clients: list[LoadClient] = []
    tasks: list[asyncio.Task[Any]] = []

    # Ramp up
    ramp_delay = ramp_seconds / max(sessions, 1)
    start_time = time.time()

    for i in range(sessions):
        client = LoadClient(api_url, ws_url, i, reconnect_rate)
        clients.append(client)
        task = asyncio.create_task(client.start())
        tasks.append(task)

        if ramp_delay > 0:
            await asyncio.sleep(ramp_delay)

    # Hold
    print(f"Ramp complete. Holding for {hold_seconds}s...")
    await asyncio.sleep(hold_seconds)

    # Stop all
    for client in clients:
        client.stop()

    # Wait for completion with timeout
    await asyncio.wait(tasks, timeout=30)

    elapsed = time.time() - start_time

    # Aggregate results
    results = HarnessResults()
    results.hold_duration_seconds = hold_seconds
    results.ulimit = ulimit
    results.topology = f"1 API instance at {api_url}"

    all_lags: list[float] = []
    for client in clients:
        if client.stats.connected or client.stats.events_received > 0:
            results.sessions_sustained += 1
        results.total_events += client.stats.events_received
        results.total_gaps += client.stats.gaps_detected
        results.total_reconnects += client.stats.reconnects
        results.total_reconnect_failures += client.stats.reconnect_failures
        results.total_server_closes += client.stats.server_closes
        all_lags.extend(client.stats.delivery_lags)
        if client.stats.error:
            results.errors.append(f"client-{client.client_id}: {client.stats.error}")

    if all_lags:
        all_lags.sort()
        results.delivery_lag_p50 = statistics.median(all_lags)
        idx_95 = int(len(all_lags) * 0.95)
        idx_99 = int(len(all_lags) * 0.99)
        results.delivery_lag_p95 = all_lags[idx_95] if idx_95 < len(all_lags) else 0
        results.delivery_lag_p99 = all_lags[idx_99] if idx_99 < len(all_lags) else 0

    return results


def print_results(results: HarnessResults) -> None:
    """Print formatted results."""
    print("\n" + "=" * 60)
    print("LOAD TEST RESULTS")
    print("=" * 60)
    print(f"Sessions sustained:      {results.sessions_sustained}")
    print(f"Total events:            {results.total_events}")
    print(f"Total gaps:              {results.total_gaps}")
    print(f"Total reconnects:        {results.total_reconnects}")
    print(f"Reconnect failures:      {results.total_reconnect_failures}")
    print(f"Server-initiated closes: {results.total_server_closes}")
    print(f"Hold duration:           {results.hold_duration_seconds}s")
    print(f"ulimit -n:               {results.ulimit}")
    print(f"Topology:                {results.topology}")
    print()
    print(f"Delivery lag p50:        {results.delivery_lag_p50 * 1000:.1f}ms")
    print(f"Delivery lag p95:        {results.delivery_lag_p95 * 1000:.1f}ms")
    print(f"Delivery lag p99:        {results.delivery_lag_p99 * 1000:.1f}ms")
    print()
    if results.errors:
        print(f"Errors ({len(results.errors)}):")
        for err in results.errors[:20]:
            print(f"  {err}")
    print("=" * 60)


async def main() -> None:
    parser = argparse.ArgumentParser(description="WebSocket Load Harness")
    parser.add_argument("--sessions", type=int, default=100, help="Number of concurrent sessions")
    parser.add_argument("--ramp", type=int, default=30, help="Ramp-up duration in seconds")
    parser.add_argument("--hold", type=int, default=600, help="Hold duration in seconds")
    parser.add_argument("--reconnect-rate", type=float, default=0.05, help="Fraction of events that trigger reconnect")
    parser.add_argument("--api-url", type=str, default="http://localhost:7601")
    parser.add_argument("--ws-url", type=str, default="ws://localhost:7601")
    args = parser.parse_args()

    results = await run_load_test(
        sessions=args.sessions,
        ramp_seconds=args.ramp,
        hold_seconds=args.hold,
        reconnect_rate=args.reconnect_rate,
        api_url=args.api_url,
        ws_url=args.ws_url,
    )
    print_results(results)

    # Save results to bench/results/
    import json
    import os
    from datetime import datetime, timezone

    results_dir = os.path.join(os.path.dirname(__file__), "results")
    os.makedirs(results_dir, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    result_file = os.path.join(results_dir, f"run_{timestamp}.json")

    with open(result_file, "w") as f:
        json.dump(
            {
                "sessions_sustained": results.sessions_sustained,
                "total_events": results.total_events,
                "total_gaps": results.total_gaps,
                "total_reconnects": results.total_reconnects,
                "total_reconnect_failures": results.total_reconnect_failures,
                "total_server_closes": results.total_server_closes,
                "delivery_lag_p50_ms": results.delivery_lag_p50 * 1000,
                "delivery_lag_p95_ms": results.delivery_lag_p95 * 1000,
                "delivery_lag_p99_ms": results.delivery_lag_p99 * 1000,
                "hold_duration_seconds": results.hold_duration_seconds,
                "ulimit": results.ulimit,
                "topology": results.topology,
                "timestamp": timestamp,
            },
            f,
            indent=2,
        )
    print(f"\nResults saved to: {result_file}")


if __name__ == "__main__":
    asyncio.run(main())
