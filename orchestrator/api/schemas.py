"""API request/response schemas — Pydantic v2."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from orchestrator.db.models import RunState, StepState
from orchestrator.events.schemas import EventKind


class CreateRunRequest(BaseModel):
    workflow: str
    input: dict[str, Any]
    idempotency_key: str | None = None


class RunResponse(BaseModel):
    id: UUID
    workflow: str
    input: dict[str, Any]
    state: RunState
    attempt: int
    fence: int
    cancel_requested: bool = False
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class StepResponse(BaseModel):
    run_id: UUID
    step_id: str
    state: StepState
    attempt: int
    input: dict[str, Any] | None = None
    output: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None

    class Config:
        from_attributes = True


class EventResponse(BaseModel):
    run_id: UUID
    seq: int
    kind: str
    payload: dict[str, Any]
    created_at: datetime

    class Config:
        from_attributes = True


class RunDetailResponse(BaseModel):
    run: RunResponse
    steps: list[StepResponse]
    latest_checkpoint_seq: int | None = None


class WorkflowResponse(BaseModel):
    name: str
    description: str
    steps: list[dict[str, str]]


class EventsPageResponse(BaseModel):
    events: list[EventResponse]
    has_more: bool


class HealthResponse(BaseModel):
    status: str
    postgres: bool = False
    sqs: bool = False


class MetricsResponse(BaseModel):
    active_connections: int
    active_runs: int
