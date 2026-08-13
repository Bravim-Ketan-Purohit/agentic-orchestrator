"""LISTEN/NOTIFY fan-out with poll fallback.

One listener per API instance on a wildcard-style approach: we LISTEN on
a per-run channel. On notify, we read events from the table and forward them.
A slow-poll fallback ensures a missed notification degrades to latency, not loss.
"""

import asyncio
from collections import defaultdict
from collections.abc import Callable, Coroutine
from typing import Any
from uuid import UUID

import asyncpg
import structlog

from orchestrator.config import settings

logger = structlog.get_logger()

# Type for notification callbacks
NotifyCallback = Callable[[UUID, int], Coroutine[Any, Any, None]]


class EventListener:
    """Manages Postgres LISTEN/NOTIFY subscriptions for run events.

    Runs a dedicated asyncpg connection for LISTEN. On notification,
    invokes registered callbacks. Poll fallback runs independently to
    catch missed notifications.
    """

    def __init__(self) -> None:
        self._conn: asyncpg.Connection | None = None
        self._subscribers: dict[UUID, list[NotifyCallback]] = defaultdict(list)
        self._poll_task: asyncio.Task[None] | None = None
        self._listen_task: asyncio.Task[None] | None = None
        self._running = False
        self._listened_channels: set[str] = set()

    async def start(self) -> None:
        """Start the listener with a dedicated connection."""
        dsn = settings.database_url.replace("+asyncpg", "").replace("postgresql", "postgresql")
        # asyncpg wants a plain postgres:// URL
        dsn = dsn.replace("postgresql+asyncpg://", "postgresql://")
        if "postgresql://" not in dsn:
            dsn = f"postgresql://orchestrator:orchestrator@localhost:7602/orchestrator"

        self._conn = await asyncpg.connect(dsn)
        self._running = True
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info("event_listener_started")

    async def stop(self) -> None:
        """Stop the listener and clean up."""
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        if self._conn and not self._conn.is_closed():
            await self._conn.close()
        self._subscribers.clear()
        self._listened_channels.clear()
        logger.info("event_listener_stopped")

    async def subscribe(self, run_id: UUID, callback: NotifyCallback) -> None:
        """Subscribe to events for a run. Starts LISTEN if not already active."""
        self._subscribers[run_id].append(callback)
        channel = f"run:{run_id}"
        if channel not in self._listened_channels and self._conn:
            await self._conn.add_listener(channel, self._on_notification)
            self._listened_channels.add(channel)
            logger.debug("listen_started", channel=channel)

    async def unsubscribe(self, run_id: UUID, callback: NotifyCallback) -> None:
        """Remove a subscription. Stops LISTEN if no more subscribers."""
        if run_id in self._subscribers:
            try:
                self._subscribers[run_id].remove(callback)
            except ValueError:
                pass
            if not self._subscribers[run_id]:
                del self._subscribers[run_id]
                channel = f"run:{run_id}"
                if channel in self._listened_channels and self._conn:
                    await self._conn.remove_listener(channel, self._on_notification)
                    self._listened_channels.discard(channel)

    def _on_notification(
        self,
        connection: asyncpg.Connection,
        pid: int,
        channel: str,
        payload: str,
    ) -> None:
        """Handle a NOTIFY — signal only, never read the payload as data."""
        # Parse run_id from channel name "run:<uuid>"
        try:
            run_id = UUID(channel.split(":", 1)[1])
            seq = int(payload)
        except (IndexError, ValueError):
            logger.warning("invalid_notification", channel=channel, payload=payload)
            return

        # Schedule callbacks
        if run_id in self._subscribers:
            for cb in self._subscribers[run_id]:
                asyncio.create_task(cb(run_id, seq))

    async def _poll_loop(self) -> None:
        """Slow-poll fallback: ensures missed notifications degrade to latency, not loss.

        Runs every notify_poll_interval_ms for all subscribed runs.
        """
        interval = settings.notify_poll_interval_ms / 1000.0
        while self._running:
            try:
                await asyncio.sleep(interval)
                # Notify all subscribers with seq=0 to trigger a re-read
                for run_id, callbacks in list(self._subscribers.items()):
                    for cb in callbacks:
                        asyncio.create_task(cb(run_id, 0))
            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("poll_loop_error")
                await asyncio.sleep(1.0)


# Singleton instance per API process
event_listener = EventListener()
