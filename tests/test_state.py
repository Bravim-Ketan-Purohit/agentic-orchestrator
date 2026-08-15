"""Tests for state management, fencing, and checkpointing."""

import pytest
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.db.models import Run, RunState
from orchestrator.state.manager import (
    FencingError,
    acquire_lease,
    check_fence,
    load_latest_checkpoint,
    write_checkpoint,
)


@pytest.mark.integration
async def test_acquire_lease_increments_fence(db_session: AsyncSession):
    """Acquiring a lease increments the fence."""
    run_id = uuid4()
    run = Run(id=run_id, workflow="research", input={"question": "test"})
    db_session.add(run)
    await db_session.flush()

    fence = await acquire_lease(db_session, run_id, "worker-1")
    assert fence == 1

    # Second acquisition increments again
    fence2 = await acquire_lease(db_session, run_id, "worker-2")
    assert fence2 == 2


@pytest.mark.integration
async def test_fence_check_success(db_session: AsyncSession):
    """check_fence returns True when fence matches."""
    run_id = uuid4()
    run = Run(id=run_id, workflow="research", input={"question": "test"})
    db_session.add(run)
    await db_session.flush()

    fence = await acquire_lease(db_session, run_id, "worker-1")
    assert await check_fence(db_session, run_id, fence) is True
    assert await check_fence(db_session, run_id, fence + 1) is False


@pytest.mark.integration
async def test_checkpoint_write_and_load(db_session: AsyncSession):
    """Checkpoints can be written and the latest loaded."""
    run_id = uuid4()
    run = Run(id=run_id, workflow="research", input={"question": "test"})
    db_session.add(run)
    await db_session.flush()

    fence = await acquire_lease(db_session, run_id, "worker-1")

    state = {"key": "value", "step": 1}
    await write_checkpoint(db_session, run_id, "step_1", state, fence)

    loaded = await load_latest_checkpoint(db_session, run_id)
    assert loaded is not None
    loaded_state, after_step, loaded_fence = loaded
    assert loaded_state == state
    assert after_step == "step_1"
    assert loaded_fence == fence


@pytest.mark.integration
async def test_checkpoint_fencing_error(db_session: AsyncSession):
    """Writing a checkpoint with wrong fence raises FencingError."""
    run_id = uuid4()
    run = Run(id=run_id, workflow="research", input={"question": "test"})
    db_session.add(run)
    await db_session.flush()

    await acquire_lease(db_session, run_id, "worker-1")

    with pytest.raises(FencingError):
        await write_checkpoint(db_session, run_id, "step_1", {"x": 1}, 999)


@pytest.mark.integration
async def test_lease_not_granted_terminal_state(db_session: AsyncSession):
    """Cannot acquire lease on a terminal-state run."""
    run_id = uuid4()
    run = Run(id=run_id, workflow="research", input={"question": "test"}, state=RunState.succeeded)
    db_session.add(run)
    await db_session.flush()

    fence = await acquire_lease(db_session, run_id, "worker-1")
    assert fence is None
