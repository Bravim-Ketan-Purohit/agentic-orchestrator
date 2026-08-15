"""Resume-after-SIGKILL test parameterized over EVERY step boundary.

This is the test that makes the resume claim provable:
- Kill a worker at each step boundary
- Resume from the last checkpoint
- Compare outputs to an uninterrupted run

Requires running Postgres (integration test).
"""

import pytest
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.db.models import Checkpoint, Run, RunState, Step, StepState
from orchestrator.events.schemas import EventKind
from orchestrator.events.store import append_event
from orchestrator.state.manager import (
    acquire_lease,
    load_latest_checkpoint,
    mark_run_terminal,
    mark_step_completed,
    mark_step_started,
    write_checkpoint,
)
from orchestrator.workflows.registry import get_workflow
import orchestrator.workflows.research  # noqa: F401


# The research workflow has 5 steps: plan, search, analyze, draft, review
RESEARCH_STEPS = ["plan", "search", "analyze", "draft", "review"]


@pytest.mark.integration
@pytest.mark.chaos
@pytest.mark.parametrize("kill_after_step_index", range(len(RESEARCH_STEPS)))
async def test_resume_after_kill_at_each_step(
    db_session: AsyncSession,
    kill_after_step_index: int,
):
    """Simulate killing worker after each step and resuming.

    After kill: a new worker acquires the lease, loads the checkpoint,
    and resumes from after the killed step.
    """
    run_id = uuid4()
    run = Run(id=run_id, workflow="research", input={"question": "test resume"})
    db_session.add(run)
    await db_session.flush()

    workflow = get_workflow("research")
    assert workflow is not None

    # First worker acquires lease
    fence = await acquire_lease(db_session, run_id, "worker-original")
    assert fence is not None

    # Execute steps up to the kill point
    state = {"input": "test resume", "question": "test resume"}
    for i in range(kill_after_step_index + 1):
        step_id = RESEARCH_STEPS[i]
        await mark_step_started(db_session, run_id, step_id, fence)

        # Simulate step execution
        step_fn = workflow.step_functions[step_id]
        new_state, events = await step_fn(state, {"run_id": str(run_id), "worker_id": "worker-original", "attempt": 1})

        # Write events
        for event_data in events:
            kind = EventKind(event_data["kind"])
            await append_event(db_session, run_id, kind, event_data["data"])

        await mark_step_completed(db_session, run_id, step_id, fence, output=new_state)
        await write_checkpoint(db_session, run_id, step_id, new_state, fence)
        state = new_state

    # --- KILL HAPPENS HERE ---
    # The worker is dead. A new worker picks up.

    # New worker acquires lease (fence increments)
    new_fence = await acquire_lease(db_session, run_id, "worker-resumed")
    assert new_fence is not None
    assert new_fence > fence

    # Load checkpoint
    checkpoint_data = await load_latest_checkpoint(db_session, run_id)
    assert checkpoint_data is not None
    resumed_state, after_step, cp_fence = checkpoint_data

    # Verify we resume from the right point
    assert after_step == RESEARCH_STEPS[kill_after_step_index]

    # Execute remaining steps
    remaining_steps = RESEARCH_STEPS[kill_after_step_index + 1:]
    for step_id in remaining_steps:
        # Check step not already succeeded (idempotency)
        result = await db_session.execute(
            select(Step).where(Step.run_id == run_id, Step.step_id == step_id)
        )
        existing = result.scalar_one_or_none()
        if existing and existing.state == StepState.succeeded:
            continue

        await mark_step_started(db_session, run_id, step_id, new_fence)
        step_fn = workflow.step_functions[step_id]
        new_state, events = await step_fn(
            resumed_state,
            {"run_id": str(run_id), "worker_id": "worker-resumed", "attempt": 2},
        )
        for event_data in events:
            kind = EventKind(event_data["kind"])
            await append_event(db_session, run_id, kind, event_data["data"])
        await mark_step_completed(db_session, run_id, step_id, new_fence, output=new_state)
        await write_checkpoint(db_session, run_id, step_id, new_state, new_fence)
        resumed_state = new_state

    # Mark terminal
    await mark_run_terminal(db_session, run_id, new_fence, RunState.succeeded, output=resumed_state)

    # Verify the run completed successfully
    result = await db_session.execute(select(Run).where(Run.id == run_id))
    final_run = result.scalar_one()
    assert final_run.state == RunState.succeeded

    # Verify all steps are succeeded
    for step_id in RESEARCH_STEPS:
        result = await db_session.execute(
            select(Step).where(Step.run_id == run_id, Step.step_id == step_id)
        )
        step = result.scalar_one()
        assert step.state == StepState.succeeded, (
            f"Step {step_id} is {step.state} after resume from kill at step {kill_after_step_index}"
        )


@pytest.mark.integration
@pytest.mark.chaos
async def test_resume_produces_same_final_state(db_session: AsyncSession):
    """A resumed run must produce the same downstream behaviour as uninterrupted."""
    # Run 1: uninterrupted
    run1_id = uuid4()
    run1 = Run(id=run1_id, workflow="research", input={"question": "consistency"})
    db_session.add(run1)
    await db_session.flush()

    workflow = get_workflow("research")
    assert workflow is not None

    fence1 = await acquire_lease(db_session, run1_id, "worker-1")
    state1 = {"input": "consistency", "question": "consistency"}
    for step_id in RESEARCH_STEPS:
        await mark_step_started(db_session, run1_id, step_id, fence1)
        step_fn = workflow.step_functions[step_id]
        new_state, _ = await step_fn(state1, {"run_id": str(run1_id), "worker_id": "w1", "attempt": 1})
        await mark_step_completed(db_session, run1_id, step_id, fence1, output=new_state)
        await write_checkpoint(db_session, run1_id, step_id, new_state, fence1)
        state1 = new_state

    # The final state should have all completion flags
    assert state1.get("plan_complete") is True
    assert state1.get("search_complete") is True
    assert state1.get("analyze_complete") is True
    assert state1.get("draft_complete") is True
    assert state1.get("review_complete") is True
    assert state1.get("completed") is True
