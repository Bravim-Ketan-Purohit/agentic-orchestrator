"""Event schemas — Pydantic v2 models. The 'kind' is a closed enum."""

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class EventKind(str, Enum):
    """Closed enum of event types. A new kind is a schema change with a migration."""

    token = "token"
    thought = "thought"
    tool_call = "tool_call"
    tool_result = "tool_result"
    step_start = "step_start"
    step_end = "step_end"
    checkpoint = "checkpoint"
    error = "error"
    done = "done"
    cancelled = "cancelled"


class EventPayload(BaseModel):
    """Base event payload."""

    run_id: UUID
    seq: int
    kind: EventKind
    data: dict[str, Any]
    created_at: datetime

    class Config:
        from_attributes = True


class StepStartPayload(BaseModel):
    step_id: str
    attempt: int


class StepEndPayload(BaseModel):
    step_id: str
    state: str
    output: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


class TokenPayload(BaseModel):
    step_id: str
    content: str
    index: int = 0


class ThoughtPayload(BaseModel):
    step_id: str
    content: str


class ToolCallPayload(BaseModel):
    step_id: str
    tool_name: str
    arguments: dict[str, Any]
    call_id: str


class ToolResultPayload(BaseModel):
    step_id: str
    call_id: str
    result: Any


class CheckpointPayload(BaseModel):
    after_step: str
    checkpoint_seq: int


class ErrorPayload(BaseModel):
    step_id: str | None = None
    message: str
    code: str | None = None


class DonePayload(BaseModel):
    final_state: str
    output: dict[str, Any] | None = None
