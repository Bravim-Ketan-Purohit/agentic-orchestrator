"""State management: checkpointing, fencing, and resumption.

State is a serializable dict passed step to step, checkpointed after every step.
Anything holding a live object reference or an open handle is not resumable.
"""

from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.db.models import Checkpoint, Run, RunState, Step, StepState
from orchestrator.events.schemas import EventKind
from orchestrator.events.store import append_event

logger = structlog.get_logger()


async def acquire_lease(
    session: AsyncSession,
    run_id: UUID,
    worker_id: str,
) -> int | None:
    """Acquire the run's lease by incrementing the fence.

    Returns the new fence value, or None if the run is not in a leaseable state.
    Uses SELECT ... FOR UPDATE to prevent races.
    """
    result = await session.execute(
        select(Run).where(Run.id == run_id).with_for_update()
    )
    run = result.scalar_one_or_none()
    if run is None:
        return None

    # Only lease runs that are queued or running (for resume)
    if run.state not in (RunState.queued, RunState.running):
        return None

    run.fence += 1
    run.owner_worker = worker_id
    run.state = RunState.running
    run.attempt += 1
    await session.flush()

    logger.info(
        "lease_acquired",
        run_id=str(run_id),
        worker_id=worker_id,
        fence=run.fence,
        attempt=run.attempt,
    )
    return run.fence


async def check_fence(session: AsyncSession, run_id: UUID, expected_fence: int) -> bool:
    """Verify that we still hold the lease (our fence matches current)."""
    result = await session.execute(
        text("SELECT fence FROM runs WHERE id = :run_id"),
        {"run_id": str(run_id)},
    )
    current_fence = result.scalar_one_or_none()
    return current_fence == expected_fence


async def write_checkpoint(
    session: AsyncSession,
    run_id: UUID,
    after_step: str,
    state: dict[str, Any],
    fence: int,
) -> int:
    """Write a checkpoint after a step completes.

    Also appends a checkpoint event. All in the same transaction.
    Returns the checkpoint seq.
    """
    # Verify fence first
    if not await check_fence(session, run_id, fence):
        raise FencingError(f"Fence mismatch for run {run_id}: expected {fence}")

    # Get next checkpoint seq
    result = await session.execute(
        text("SELECT COALESCE(MAX(seq), 0) + 1 FROM checkpoints WHERE run_id = :run_id"),
        {"run_id": str(run_id)},
    )
    next_seq: int = result.scalar_one()

    checkpoint = Checkpoint(
        run_id=run_id,
        seq=next_seq,
        after_step=after_step,
        state=state,
        fence=fence,
    )
    session.add(checkpoint)

    # Emit checkpoint event
    await append_event(
        session,
        run_id,
        EventKind.checkpoint,
        {"after_step": after_step, "checkpoint_seq": next_seq},
    )

    logger.info(
        "checkpoint_written",
        run_id=str(run_id),
        after_step=after_step,
        checkpoint_seq=next_seq,
        fence=fence,
    )
    return next_seq


async def load_latest_checkpoint(
    session: AsyncSession,
    run_id: UUID,
) -> tuple[dict[str, Any], str, int] | None:
    """Load the latest checkpoint for a run.

    Returns (state_dict, after_step, fence) or None if no checkpoint exists.
    """
    result = await session.execute(
        select(Checkpoint)
        .where(Checkpoint.run_id == run_id)
        .order_by(Checkpoint.seq.desc())
        .limit(1)
    )
    cp = result.scalar_one_or_none()
    if cp is None:
        return None
    return cp.state, cp.after_step, cp.fence


async def mark_step_started(
    session: AsyncSession,
    run_id: UUID,
    step_id: str,
    fence: int,
    attempt: int = 1,
) -> None:
    """Record a step as started. Emits step_start event."""
    if not await check_fence(session, run_id, fence):
        raise FencingError(f"Fence mismatch for run {run_id}")

    # Upsert step
    result = await session.execute(
        select(Step).where(Step.run_id == run_id, Step.step_id == step_id)
    )
    step = result.scalar_one_or_none()

    if step is None:
        step = Step(
            run_id=run_id,
            step_id=step_id,
            state=StepState.running,
            attempt=attempt,
        )
        session.add(step)
    else:
        # Already succeeded — skip on replay
        if step.state == StepState.succeeded:
            return
        step.state = StepState.running
        step.attempt = attempt

    await session.flush()

    await append_event(
        session,
        run_id,
        EventKind.step_start,
        {"step_id": step_id, "attempt": attempt},
    )


async def mark_step_completed(
    session: AsyncSession,
    run_id: UUID,
    step_id: str,
    fence: int,
    output: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
    state: StepState = StepState.succeeded,
) -> None:
    """Record a step as completed. Emits step_end event."""
    if not await check_fence(session, run_id, fence):
        raise FencingError(f"Fence mismatch for run {run_id}")

    result = await session.execute(
        select(Step).where(Step.run_id == run_id, Step.step_id == step_id)
    )
    step = result.scalar_one()
    step.state = state
    step.output = output
    step.error = error

    await append_event(
        session,
        run_id,
        EventKind.step_end,
        {"step_id": step_id, "state": state.value, "output": output, "error": error},
    )


async def mark_run_terminal(
    session: AsyncSession,
    run_id: UUID,
    fence: int,
    terminal_state: RunState,
    output: dict[str, Any] | None = None,
) -> None:
    """Transition a run to a terminal state. Emits done/cancelled event.

    Also writes an outbox message for SNS.
    """
    from orchestrator.outbox.writer import write_outbox_message

    if not await check_fence(session, run_id, fence):
        raise FencingError(f"Fence mismatch for run {run_id}")

    result = await session.execute(
        select(Run).where(Run.id == run_id).with_for_update()
    )
    run = result.scalar_one()
    run.state = terminal_state
    run.owner_worker = None

    # Emit appropriate event
    if terminal_state == RunState.cancelled:
        await append_event(
            session, run_id, EventKind.cancelled, {"final_state": "cancelled"}
        )
    else:
        await append_event(
            session,
            run_id,
            EventKind.done,
            {"final_state": terminal_state.value, "output": output},
        )

    # Transactional outbox — publish AFTER this transaction commits
    await write_outbox_message(
        session,
        run_id=run_id,
        workflow=run.workflow,
        terminal_state=terminal_state.value,
    )

    logger.info(
        "run_terminal",
        run_id=str(run_id),
        state=terminal_state.value,
        fence=fence,
    )


class FencingError(Exception):
    """Raised when a fencing check fails — the worker lost its lease."""

    pass
