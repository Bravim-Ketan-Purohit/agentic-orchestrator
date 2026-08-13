"""Research workflow: a multi-step agent workflow for demonstration.

Steps:
1. plan — Break the research question into sub-questions
2. search — Gather information for each sub-question
3. analyze — Synthesize findings
4. draft — Write a draft response
5. review — Self-review and improve

Each step is a pure-ish function: takes state dict, returns (new_state, events).
No open handles, no live object references — fully serializable and resumable.
"""

import asyncio
import hashlib
import random
from typing import Any

from orchestrator.workflows.registry import WorkflowDefinition, register_workflow

research_workflow = WorkflowDefinition(
    name="research",
    description="Multi-step research agent: plan, search, analyze, draft, review",
)


@research_workflow.step("plan", name="Plan Research", description="Break question into sub-questions")
async def plan_step(
    state: dict[str, Any],
    context: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Plan the research by breaking the question into sub-questions."""
    question = state.get("question", state.get("input", ""))
    # Simulate LLM thinking time
    await asyncio.sleep(random.uniform(0.5, 1.5))

    sub_questions = [
        f"What are the key aspects of: {question}?",
        f"What evidence supports this: {question}?",
        f"What are the counterarguments to: {question}?",
    ]

    new_state = {
        **state,
        "sub_questions": sub_questions,
        "plan_complete": True,
    }

    events = [
        {"kind": "thought", "data": {"step_id": "plan", "content": f"Planning research for: {question}"}},
    ]

    # Emit tokens to simulate streaming
    for i, sq in enumerate(sub_questions):
        events.append({"kind": "token", "data": {"step_id": "plan", "content": f"Sub-question {i + 1}: {sq}\n", "index": i}})

    return new_state, events


@research_workflow.step("search", name="Search", description="Gather information for each sub-question")
async def search_step(
    state: dict[str, Any],
    context: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Search for information on each sub-question."""
    sub_questions = state.get("sub_questions", [])
    findings: list[dict[str, str]] = []

    events: list[dict[str, Any]] = []

    for i, sq in enumerate(sub_questions):
        await asyncio.sleep(random.uniform(0.3, 1.0))
        finding = {
            "question": sq,
            "answer": f"Finding for '{sq}': [simulated research result {hashlib.md5(sq.encode()).hexdigest()[:8]}]",
        }
        findings.append(finding)
        events.append({
            "kind": "tool_call",
            "data": {"step_id": "search", "tool_name": "search", "arguments": {"query": sq}, "call_id": f"search_{i}"},
        })
        events.append({
            "kind": "tool_result",
            "data": {"step_id": "search", "call_id": f"search_{i}", "result": finding["answer"]},
        })

    new_state = {**state, "findings": findings, "search_complete": True}
    return new_state, events


@research_workflow.step("analyze", name="Analyze", description="Synthesize findings")
async def analyze_step(
    state: dict[str, Any],
    context: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Analyze and synthesize the findings."""
    findings = state.get("findings", [])
    await asyncio.sleep(random.uniform(0.5, 1.5))

    analysis = f"Synthesis of {len(findings)} findings: [comprehensive analysis based on gathered evidence]"

    events = [
        {"kind": "thought", "data": {"step_id": "analyze", "content": f"Analyzing {len(findings)} findings..."}},
        {"kind": "token", "data": {"step_id": "analyze", "content": analysis, "index": 0}},
    ]

    new_state = {**state, "analysis": analysis, "analyze_complete": True}
    return new_state, events


@research_workflow.step("draft", name="Draft", description="Write a draft response")
async def draft_step(
    state: dict[str, Any],
    context: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Draft the final response."""
    analysis = state.get("analysis", "")
    question = state.get("question", state.get("input", ""))
    await asyncio.sleep(random.uniform(0.5, 2.0))

    # Simulate token-by-token output
    draft_parts = [
        f"Based on research into '{question}':\n\n",
        "Key findings:\n",
        f"- {analysis}\n",
        "\nConclusion: The evidence suggests a nuanced answer.\n",
    ]

    events: list[dict[str, Any]] = []
    full_draft = ""
    for i, part in enumerate(draft_parts):
        full_draft += part
        events.append({"kind": "token", "data": {"step_id": "draft", "content": part, "index": i}})

    new_state = {**state, "draft": full_draft, "draft_complete": True}
    return new_state, events


@research_workflow.step("review", name="Review", description="Self-review and improve")
async def review_step(
    state: dict[str, Any],
    context: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Review the draft and produce final output."""
    draft = state.get("draft", "")
    await asyncio.sleep(random.uniform(0.3, 1.0))

    final_output = f"[REVIEWED] {draft}"

    events = [
        {"kind": "thought", "data": {"step_id": "review", "content": "Reviewing draft for accuracy and completeness..."}},
        {"kind": "token", "data": {"step_id": "review", "content": final_output, "index": 0}},
    ]

    new_state = {
        **state,
        "final_output": final_output,
        "review_complete": True,
        "completed": True,
    }
    return new_state, events


# Register on import
register_workflow(research_workflow)
