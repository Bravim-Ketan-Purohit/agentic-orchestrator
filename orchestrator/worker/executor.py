"""Run executor: executes workflow steps with checkpointing and fencing.

The executor:
1. Acquires the lease (fence)
2. Loads the latest checkpoint (if resuming)
3. Executes steps from after the checkpoint
4. After each step: writes step row, checkpoint, events — ONE transaction
5. On cancel: checkpoints and transitions cleanly
"""

from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import select

from orchestrator.db.engine import async_session_factory
from orchestrator.db.models import Run, RunState, Step, StepState
from orchestrator.events.schemas import EventKind
from orchestrator.events.store import append_event
from orchestrator.state.manager import (
    FencingError,
    acquire_lease,
    check_fence,
    load_latest_checkpoint,
    mark_run_terminal,
    mark_step_completed,
    mark_step_started,
    write_checkpoint,
)
from orchestrator.workflows.registry import get_workflow

logger = structlog.get_logger()


async def execute_run(
    run_id: UUID,
    worker_id: str,
    attempt: int,
) -> bool:
    """Execute a run's workflow steps.

    Returns True on successful completion, False on failure.
    """
    log = logger.bind(run_id=str(run_id), worker_id=worker_id, attempt=attempt)

    # Phase 1: Acquire lease
    async with async_session_factory() as session:
        async with session.begin():
            fence = await acquire_lease(session, run_id, worker_id)
            if fence is None:
                log.warning("lease_acquisition_failed")
                return False

            # Load run details
            result = await session.execute(select(Run).where(Run.id == run_id))
            run = result.scalar_one()
            workflow_name = run.workflow
            run_input = run.input

    log = log.bind(fence=fence, workflow=workflow_name)
    log.info("execution_started")

    # Phase 2: Load workflow
    workflow = get_workflow(workflow_name)
    if workflow is None:
        log.error("workflow_not_found", workflow=workflow_name)
        async with async_session_factory() as session:
            async with session.begin():
                await mark_run_terminal(
                    session, run_id, fence, RunState.failed,
                    output={"error": f"Workflow '{workflow_name}' not found"},
                )
        return True  # Message should be deleted (won't succeed on retry)

    # Phase 3: Load checkpoint (for resume)
    state: dict[str, Any] = {"input": run_input.get("question", str(run_input)), **run_input}
    start_after_step: str | None = None

    async with async_session_factory() as session:
        async with session.begin():
            checkpoint_data = await load_latest_checkpoint(session, run_id)
            if checkpoint_data:
                state, start_after_step, cp_fence = checkpoint_data
                log.info(
                    "resuming_from_checkpoint",
                    after_step=start_after_step,
                    checkpoint_fence=cp_fence,
                )

    # Phase 4: Execute steps
    steps = workflow.steps
    start_index = 0

    if start_after_step:
        for i, step_def in enumerate(steps):
            if step_def.id == start_after_step:
                start_index = i + 1
                break

    try:
        for step_def in steps[start_index:]:
            step_id = step_def.id

            # Check for cancel request
            async with async_session_factory() as session:
                async with session.begin():
                    result = await session.execute(select(Run).where(Run.id == run_id))
                    run = result.scalar_one()
                    if run.cancel_requested:
                        log.info("cancel_detected", at_step=step_id)
                        await _handle_cancel(run_id, fence, state, step_id)
                        return True

            log.info("step_executing", step_id=step_id)

            # Check if step already succeeded (idempotency)
            async with async_session_factory() as session:
                async with session.begin():
                    result = await session.execute(
                        select(Step).where(
                            Step.run_id == run_id, Step.step_id == step_id
                        )
                    )
                    existing_step = result.scalar_one_or_none()
                    if existing_step and existing_step.state == StepState.succeeded:
                        log.info("step_already_succeeded_skipping", step_id=step_id)
                        # Load its output into state
                        if existing_step.output:
                            state.update(existing_step.output)
                        continue

            # Mark step started
            async with async_session_factory() as session:
                async with session.begin():
                    if not await check_fence(session, run_id, fence):
                        raise FencingError("Lost lease")
                    await mark_step_started(session, run_id, step_id, fence, attempt)

            # Execute the step function
            step_fn = workflow.step_functions[step_id]
            context = {"run_id": str(run_id), "worker_id": worker_id, "attempt": attempt}
            new_state, events = await step_fn(state, context)

            # Commit: step completion + events + checkpoint — ONE transaction
            async with async_session_factory() as session:
                async with session.begin():
                    if not await check_fence(session, run_id, fence):
                        raise FencingError("Lost lease during commit")

                    # Emit step events
                    for event_data in events:
                        kind = EventKind(event_data["kind"])
                        await append_event(session, run_id, kind, event_data["data"])

                    # Mark step completed
                    await mark_step_completed(
                        session, run_id, step_id, fence,
                        output=new_state,
                    )

                    # Write checkpoint
                    await write_checkpoint(session, run_id, step_id, new_state, fence)

            state = new_state
            log.info("step_completed", step_id=step_id)

        # All steps done — terminal success
        async with async_session_factory() as session:
            async with session.begin():
                await mark_run_terminal(
                    session, run_id, fence, RunState.succeeded,
                    output=state.get("final_output"),
                )

        log.info("run_succeeded")
        return True

    except FencingError as e:
        log.warning("fencing_error", error=str(e))
        return False  # Let SQS redeliver
    except Exception as e:
        log.exception("execution_error", error=str(e))
        try:
            async with async_session_factory() as session:
                async with session.begin():
                    if await check_fence(session, run_id, fence):
                        await append_event(
                            session, run_id, EventKind.error,
                            {"message": str(e), "step_id": None},
                        )
                        await mark_run_terminal(
                            session, run_id, fence, RunState.failed,
                            output={"error": str(e)},
                        )
        except Exception:
            log.exception("failed_to_mark_terminal")
        return True  # Don't retry on application errors


async def _handle_cancel(
    run_id: UUID,
    fence: int,
    state: dict[str, Any],
    at_step: str,
) -> None:
    """Handle cooperative cancel: checkpoint current state, transition to cancelled."""
    async with async_session_factory() as session:
        async with session.begin():
            if not await check_fence(session, run_id, fence):
                return
            await write_checkpoint(session, run_id, f"cancel_at_{at_step}", state, fence)
            await mark_run_terminal(session, run_id, fence, RunState.cancelled)
