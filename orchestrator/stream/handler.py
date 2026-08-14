"""WebSocket handler: replay from last_seq, then go live.

The replay-to-live handoff must not drop or duplicate:
1. Subscribe to LISTEN/NOTIFY FIRST (before replay)
2. Buffer incoming notifications
3. Replay from DB where seq > last_seq
4. Flush buffer, discarding anything at or below last replayed seq
5. Go live

This ordering is what guarantees no gaps.
"""

import asyncio
import json
from typing import Any
from uuid import UUID

import structlog
from fastapi import WebSocket, WebSocketDisconnect

from orchestrator.db.engine import async_session_factory
from orchestrator.events.listener import event_listener
from orchestrator.events.store import get_events_after
from orchestrator.stream.connection import (
    ManagedConnection,
    connection_manager,
)

logger = structlog.get_logger()


async def handle_websocket_stream(
    websocket: WebSocket,
    run_id: UUID,
    last_seq: int,
) -> None:
    """Handle a WebSocket connection for streaming run events.

    Implements the replay-to-live handoff without gaps or duplicates.
    """
    log = logger.bind(run_id=str(run_id), last_seq=last_seq)
    log.info("ws_connection_started")

    conn = ManagedConnection(websocket, run_id, last_seq)
    connection_manager.add(conn)
    await conn.start()

    # Buffer for events arriving during replay
    buffer: list[tuple[UUID, int]] = []
    buffer_lock = asyncio.Lock()

    async def on_notify(notified_run_id: UUID, seq: int) -> None:
        """Buffer notifications during replay, then forward live."""
        async with buffer_lock:
            buffer.append((notified_run_id, seq))

    try:
        # Step 1: Subscribe FIRST (before replay)
        await event_listener.subscribe(run_id, on_notify)

        # Step 2: Replay from DB
        cursor = last_seq
        async with async_session_factory() as session:
            events = await get_events_after(session, run_id, cursor)
            for event in events:
                event_data = _event_to_dict(event)
                conn.enqueue(event_data)
                cursor = max(cursor, event.seq)

        log.info("replay_complete", replayed_count=cursor - last_seq, cursor=cursor)
        conn.cursor = cursor

        # Step 3: Flush buffer, discarding anything at or below cursor
        async with buffer_lock:
            for _, seq in buffer:
                if seq > cursor:
                    # Read the new events from DB
                    async with async_session_factory() as session:
                        new_events = await get_events_after(session, run_id, cursor)
                        for event in new_events:
                            event_data = _event_to_dict(event)
                            conn.enqueue(event_data)
                            cursor = max(cursor, event.seq)
                    conn.cursor = cursor
            buffer.clear()

        # Step 4: Switch to live mode — notifications now go directly
        async def on_notify_live(notified_run_id: UUID, seq: int) -> None:
            """Forward live events."""
            if seq > conn.cursor:
                async with async_session_factory() as session:
                    new_events = await get_events_after(session, run_id, conn.cursor)
                    for event in new_events:
                        event_data = _event_to_dict(event)
                        if event.seq > conn.cursor:
                            conn.enqueue(event_data)
                            conn.cursor = max(conn.cursor, event.seq)

        # Replace the buffer callback with the live callback
        await event_listener.unsubscribe(run_id, on_notify)
        await event_listener.subscribe(run_id, on_notify_live)

        # Keep connection alive, waiting for client messages or disconnect
        while not conn.is_closed:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=60.0)
                # Handle client messages (e.g., pong responses)
                msg = json.loads(data)
                if msg.get("type") == "pong":
                    pass  # Heartbeat response, connection is alive
            except asyncio.TimeoutError:
                continue
            except WebSocketDisconnect:
                break
            except Exception:
                break

    except WebSocketDisconnect:
        log.info("ws_client_disconnected")
    except Exception:
        log.exception("ws_handler_error")
    finally:
        await event_listener.unsubscribe(run_id, on_notify)
        try:
            await event_listener.unsubscribe(run_id, on_notify_live)  # type: ignore
        except Exception:
            pass
        await conn.stop()
        connection_manager.remove(conn)
        log.info("ws_connection_closed")


def _event_to_dict(event: Any) -> dict[str, Any]:
    """Convert an Event model instance to a dict for WebSocket transmission."""
    return {
        "run_id": str(event.run_id),
        "seq": event.seq,
        "kind": event.kind,
        "data": event.payload,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }
