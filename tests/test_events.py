"""Tests for gap-free event allocation and replay."""

import pytest
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.db.models import Event, Run, RunState
from orchestrator.events.schemas import EventKind
from orchestrator.events.store import append_event, get_events_after, get_latest_seq


@pytest.mark.integration
async def test_gap_free_sequence_allocation(db_session: AsyncSession):
    """Events must have gap-free per-run sequence numbers."""
    run_id = uuid4()
    run = Run(id=run_id, workflow="research", input={"question": "test"})
    db_session.add(run)
    await db_session.flush()

    # Append several events
    seqs = []
    for i in range(10):
        seq = await append_event(
            db_session, run_id, EventKind.token,
            {"step_id": "test", "content": f"token {i}", "index": i},
        )
        seqs.append(seq)

    # Assert gap-free monotonic +1
    assert seqs == list(range(1, 11))


@pytest.mark.integration
async def test_events_replay_from_seq(db_session: AsyncSession):
    """get_events_after returns only events after the given seq."""
    run_id = uuid4()
    run = Run(id=run_id, workflow="research", input={"question": "test"})
    db_session.add(run)
    await db_session.flush()

    for i in range(5):
        await append_event(
            db_session, run_id, EventKind.token,
            {"step_id": "test", "content": f"tok {i}", "index": i},
        )

    # Read from seq 3 onward
    events = await get_events_after(db_session, run_id, 3)
    assert len(events) == 2
    assert events[0].seq == 4
    assert events[1].seq == 5


@pytest.mark.integration
async def test_latest_seq_empty_run(db_session: AsyncSession):
    """Latest seq for a run with no events should be 0."""
    run_id = uuid4()
    run = Run(id=run_id, workflow="research", input={"question": "test"})
    db_session.add(run)
    await db_session.flush()

    latest = await get_latest_seq(db_session, run_id)
    assert latest == 0
