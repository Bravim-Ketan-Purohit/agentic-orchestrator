"""Workflow registry: declare workflows in code, register, and look up."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel


class StepDefinition(BaseModel):
    """A workflow step definition."""

    id: str
    name: str
    description: str = ""


@dataclass
class WorkflowDefinition:
    """A workflow declared in code. Steps are pure-ish functions."""

    name: str
    description: str = ""
    steps: list[StepDefinition] = field(default_factory=list)
    # Each step function takes (state, step_context) -> (new_state, events)
    step_functions: dict[str, Callable[..., Awaitable[tuple[dict[str, Any], list[dict[str, Any]]]]]] = (
        field(default_factory=dict)
    )

    def step(
        self,
        step_id: str,
        name: str = "",
        description: str = "",
    ) -> Callable[..., Any]:
        """Decorator to register a step function."""

        def decorator(
            fn: Callable[..., Awaitable[tuple[dict[str, Any], list[dict[str, Any]]]]],
        ) -> Callable[..., Awaitable[tuple[dict[str, Any], list[dict[str, Any]]]]]:
            step_def = StepDefinition(
                id=step_id,
                name=name or fn.__name__,
                description=description,
            )
            self.steps.append(step_def)
            self.step_functions[step_id] = fn
            return fn

        return decorator


# Global registry
_registry: dict[str, WorkflowDefinition] = {}


def register_workflow(workflow: WorkflowDefinition) -> None:
    """Register a workflow definition."""
    _registry[workflow.name] = workflow


def get_workflow(name: str) -> WorkflowDefinition | None:
    """Look up a registered workflow."""
    return _registry.get(name)


def list_workflows() -> list[WorkflowDefinition]:
    """Return all registered workflows."""
    return list(_registry.values())
