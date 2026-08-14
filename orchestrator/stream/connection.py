"""WebSocket connection manager with bounded send queue.

Key behaviors:
- Bounded per-connection send queue (overflow → close with reconnect code)
- Heartbeat ping/pong (20s)
- Origin validation on handshake
- One slow client cannot OOM the instance
"""

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

import structlog
from fastapi import WebSocket, WebSocketDisconnect, status

from orchestrator.config import settings

logger = structlog.get_logger()

# WebSocket close codes
WS_CLOSE_NORMAL = 1000
WS_CLOSE_GOING_AWAY = 1001
WS_CLOSE_RECONNECT = 4000  # Custom: client should reconnect with last_seq
WS_CLOSE_UNAUTHORIZED = 4001


class ManagedConnection:
    """A single managed WebSocket connection with bounded send queue."""

    def __init__(self, websocket: WebSocket, run_id: UUID, last_seq: int) -> None:
        self.websocket = websocket
        self.run_id = run_id
        self.last_seq = last_seq  # Client's last seen seq
        self.cursor = last_seq  # Our cursor for what we've sent
        self._queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(
            maxsize=settings.ws_send_queue_max
        )
        self._send_task: asyncio.Task[None] | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._closed = False
        self._log = logger.bind(run_id=str(run_id), last_seq=last_seq)

    async def start(self) -> None:
        """Start the send loop and heartbeat."""
        self._send_task = asyncio.create_task(self._send_loop())
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def stop(self) -> None:
        """Stop and clean up."""
        self._closed = True
        if self._send_task:
            self._send_task.cancel()
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        try:
            if self._send_task:
                await self._send_task
        except asyncio.CancelledError:
            pass
        try:
            if self._heartbeat_task:
                await self._heartbeat_task
        except asyncio.CancelledError:
            pass

    def enqueue(self, event: dict[str, Any]) -> bool:
        """Enqueue an event for sending. Returns False if queue is full (triggers close)."""
        if self._closed:
            return False
        try:
            self._queue.put_nowait(event)
            return True
        except asyncio.QueueFull:
            # Bounded queue overflow — close with reconnect code
            self._log.warning("send_queue_overflow", queue_size=self._queue.qsize())
            asyncio.create_task(self._close_overflow())
            return False

    async def _close_overflow(self) -> None:
        """Close the connection on queue overflow, telling client to reconnect."""
        self._closed = True
        try:
            await self.websocket.close(
                code=WS_CLOSE_RECONNECT,
                reason="Send queue overflow, reconnect with last_seq",
            )
        except Exception:
            pass

    async def _send_loop(self) -> None:
        """Drain the send queue and push to the WebSocket."""
        while not self._closed:
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                if event is None:
                    break
                await self.websocket.send_text(json.dumps(event))
                # Update cursor
                if "seq" in event:
                    self.cursor = max(self.cursor, event["seq"])
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                return
            except (WebSocketDisconnect, RuntimeError):
                self._closed = True
                return
            except Exception:
                self._log.exception("send_error")
                self._closed = True
                return

    async def _heartbeat_loop(self) -> None:
        """Ping/pong heartbeat to detect dead connections."""
        interval = settings.ws_heartbeat_interval
        while not self._closed:
            try:
                await asyncio.sleep(interval)
                await self.websocket.send_text(json.dumps({"type": "ping"}))
            except asyncio.CancelledError:
                return
            except (WebSocketDisconnect, RuntimeError):
                self._closed = True
                return
            except Exception:
                self._closed = True
                return

    @property
    def is_closed(self) -> bool:
        return self._closed


class ConnectionManager:
    """Manages all active WebSocket connections across runs."""

    def __init__(self) -> None:
        # run_id -> list of connections
        self._connections: dict[UUID, list[ManagedConnection]] = {}

    def add(self, conn: ManagedConnection) -> None:
        """Register a connection."""
        if conn.run_id not in self._connections:
            self._connections[conn.run_id] = []
        self._connections[conn.run_id].append(conn)

    def remove(self, conn: ManagedConnection) -> None:
        """Unregister a connection."""
        if conn.run_id in self._connections:
            self._connections[conn.run_id] = [
                c for c in self._connections[conn.run_id] if c is not conn
            ]
            if not self._connections[conn.run_id]:
                del self._connections[conn.run_id]

    def get_connections(self, run_id: UUID) -> list[ManagedConnection]:
        """Get all connections for a run."""
        return self._connections.get(run_id, [])

    def broadcast(self, run_id: UUID, event: dict[str, Any]) -> None:
        """Send event to all connections for a run (local instance only)."""
        for conn in self.get_connections(run_id):
            if not conn.is_closed:
                seq = event.get("seq", 0)
                # Only send if seq > what the connection has already seen
                if seq > conn.cursor:
                    conn.enqueue(event)

    @property
    def total_connections(self) -> int:
        return sum(len(conns) for conns in self._connections.values())

    @property
    def active_runs(self) -> int:
        return len(self._connections)


# Singleton per API instance
connection_manager = ConnectionManager()


def validate_origin(origin: str | None) -> bool:
    """Validate the WebSocket Origin header.

    WebSockets are NOT covered by CORS — this is the standard oversight.
    In local dev (no origin header from CLI tools/load harness), allow the connection.
    """
    if not origin:
        # Allow connections without origin (CLI tools, load harness, Postman)
        return True
    allowed = settings.ws_origins
    return origin in allowed
