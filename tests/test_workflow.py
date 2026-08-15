"""Tests for workflow registration and step execution."""

import pytest

from orchestrator.workflows.registry import get_workflow, list_workflows
import orchestrator.workflows.research  # noqa: F401


def test_research_workflow_registered():
    """The research workflow is registered on import."""
    workflow = get_workflow("research")
    assert workflow is not None
    assert workflow.name == "research"


def test_research_workflow_has_five_steps():
    """Research workflow has plan, search, analyze, draft, review."""
    workflow = get_workflow("research")
    assert workflow is not None
    step_ids = [s.id for s in workflow.steps]
    assert step_ids == ["plan", "search", "analyze", "draft", "review"]


def test_list_workflows():
    """list_workflows returns all registered workflows."""
    workflows = list_workflows()
    names = [w.name for w in workflows]
    assert "research" in names


@pytest.mark.asyncio
async def test_plan_step_returns_state_and_events():
    """Plan step produces valid state and events."""
    workflow = get_workflow("research")
    assert workflow is not None
    step_fn = workflow.step_functions["plan"]
    state = {"question": "What is distributed systems?"}
    new_state, events = await step_fn(state, {"run_id": "test", "worker_id": "w", "attempt": 1})

    assert new_state["plan_complete"] is True
    assert "sub_questions" in new_state
    assert len(events) > 0
    # All events have a valid kind
    valid_kinds = {"token", "thought", "tool_call", "tool_result", "step_start", "step_end", "checkpoint", "error", "done", "cancelled"}
    for ev in events:
        assert ev["kind"] in valid_kinds
