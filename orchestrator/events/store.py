"""Event persistence with gap-free per-run sequence allocation.

The sequence number is allocated in the SAME transaction that writes the event.
Never a global sequence — rolled-back transactions would leave holes.
"""

from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.db.models import Event
from orchestrator.events.schemas import EventKind

logger = structlog.get_logger()


async def append_event(
    session: AsyncSession,
    run_id: UUID,
    kind: EventKind,
    payload: dict[str, Any],
) -> int:
    """Append an event with the next gap-free sequence number for this run.

    MUST be called within an existing transaction. The seq is allocated by
    SELECT max(seq)+1 ... FOR UPDATE on the run row to prevent concurrent
    allocations from creating gaps.

    Returns the allocated seq number.
    """
    # Serialise seq allocation by locking the RUN row first. Postgres rejects
    # FOR UPDATE on an aggregate query, so the lock and the max() must be two
    # statements: the row lock is what prevents concurrent allocations from
    # producing duplicate or gapped sequence numbers.
    await session.execute(
        text("SELECT id FROM runs WHERE id = :run_id FOR UPDATE"),
        {"run_id": str(run_id)},
    )
    result = await session.execute(
        text("""
            SELECT COALESCE(MAX(seq), 0) + 1 AS next_seq
            FROM events
            WHERE run_id = :run_id
        """),
        {"run_id": str(run_id)},
    )
    next_seq: int = result.scalar_one()

    event = Event(
        run_id=run_id,
        seq=next_seq,
        kind=kind.value,
        payload=payload,
    )
    session.add(event)
    await session.flush()

    # pg_notify signal only — never the payload
    await session.execute(
        text("SELECT pg_notify(:channel, :seq)"),
        {"channel": f"run:{run_id}", "seq": str(next_seq)},
    )

    logger.debug(
        "event_appended",
        run_id=str(run_id),
        seq=next_seq,
        kind=kind.value,
    )
    return next_seq


async def get_events_after(
    session: AsyncSession,
    run_id: UUID,
    after_seq: int,
    limit: int = 1000,
) -> list[Event]:
    """Read events for a run with seq > after_seq, ordered by seq."""
    result = await session.execute(
        select(Event)
        .where(Event.run_id == run_id, Event.seq > after_seq)
        .order_by(Event.seq)
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_latest_seq(session: AsyncSession, run_id: UUID) -> int:
    """Get the latest sequence number for a run, or 0 if no events."""
    result = await session.execute(
        text("SELECT COALESCE(MAX(seq), 0) FROM events WHERE run_id = :run_id"),
        {"run_id": str(run_id)},
    )
    return result.scalar_one()
