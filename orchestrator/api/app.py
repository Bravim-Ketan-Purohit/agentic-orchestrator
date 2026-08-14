"""FastAPI application: REST API + WebSocket endpoint.

Two instances run in dev (:7601 and :7605) to prove cross-instance fan-out.
"""

import json
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

import aioboto3
import structlog
from fastapi import Depends, FastAPI, HTTPException, Query, WebSocket, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.api.schemas import (
    CreateRunRequest,
    EventResponse,
    EventsPageResponse,
    HealthResponse,
    MetricsResponse,
    RunDetailResponse,
    RunResponse,
    StepResponse,
    WorkflowResponse,
)
from orchestrator.config import settings
from orchestrator.db.engine import async_session_factory, engine, get_session
from orchestrator.db.models import Checkpoint, Event, Run, RunState, Step
from orchestrator.events.listener import event_listener
from orchestrator.logging import setup_logging
from orchestrator.stream.connection import (
    WS_CLOSE_UNAUTHORIZED,
    connection_manager,
    validate_origin,
)
from orchestrator.stream.handler import handle_websocket_stream
from orchestrator.workflows.registry import get_workflow, list_workflows

# Ensure workflows are registered
import orchestrator.workflows.research  # noqa: F401

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: start/stop event listener."""
    setup_logging()
    await event_listener.start()
    logger.info("api_started", port=settings.api_port)
    yield
    await event_listener.stop()
    await engine.dispose()
    logger.info("api_stopped")


app = FastAPI(
    title="Agentic Orchestrator",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ws_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- REST Endpoints ---


@app.post("/v1/runs", response_model=RunResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_run(
    request: CreateRunRequest,
    session: AsyncSession = Depends(get_session),
) -> Any:
    """Submit a new run. Enqueues to SQS for worker processing."""
    # Validate workflow exists
    workflow = get_workflow(request.workflow)
    if workflow is None:
        raise HTTPException(
            status_code=400,
            detail=f"Workflow '{request.workflow}' not found",
        )

    # Check idempotency
    if request.idempotency_key:
        result = await session.execute(
            select(Run).where(Run.idempotency_key == request.idempotency_key)
        )
        existing = result.scalar_one_or_none()
        if existing:
            return existing

    # Create run
    run = Run(
        workflow=request.workflow,
        input=request.input,
        idempotency_key=request.idempotency_key,
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)

    # Enqueue to SQS
    await _enqueue_run(run.id)

    logger.info("run_created", run_id=str(run.id), workflow=request.workflow)
    return run


@app.get("/v1/runs/{run_id}", response_model=RunDetailResponse)
async def get_run(
    run_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> Any:
    """Get run details with steps and latest checkpoint."""
    result = await session.execute(select(Run).where(Run.id == run_id))
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    # Get steps
    step_result = await session.execute(
        select(Step).where(Step.run_id == run_id)
    )
    steps = list(step_result.scalars().all())

    # Get latest checkpoint seq
    cp_result = await session.execute(
        text("SELECT COALESCE(MAX(seq), 0) FROM checkpoints WHERE run_id = :run_id"),
        {"run_id": str(run_id)},
    )
    latest_cp_seq = cp_result.scalar_one()

    return RunDetailResponse(
        run=RunResponse.model_validate(run),
        steps=[StepResponse.model_validate(s) for s in steps],
        latest_checkpoint_seq=latest_cp_seq if latest_cp_seq > 0 else None,
    )


@app.get("/v1/runs/{run_id}/events", response_model=EventsPageResponse)
async def get_run_events(
    run_id: UUID,
    after: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
    session: AsyncSession = Depends(get_session),
) -> Any:
    """Get paged event history (the non-WS read path)."""
    # Verify run exists
    result = await session.execute(select(Run).where(Run.id == run_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Run not found")

    event_result = await session.execute(
        select(Event)
        .where(Event.run_id == run_id, Event.seq > after)
        .order_by(Event.seq)
        .limit(limit + 1)
    )
    events = list(event_result.scalars().all())

    has_more = len(events) > limit
    if has_more:
        events = events[:limit]

    return EventsPageResponse(
        events=[EventResponse.model_validate(e) for e in events],
        has_more=has_more,
    )


@app.post("/v1/runs/{run_id}/cancel", status_code=status.HTTP_202_ACCEPTED)
async def cancel_run(
    run_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    """Request cooperative cancel. The worker checks between steps."""
    result = await session.execute(
        select(Run).where(Run.id == run_id).with_for_update()
    )
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    if run.state in (RunState.succeeded, RunState.failed, RunState.cancelled):
        raise HTTPException(status_code=409, detail=f"Run already in terminal state: {run.state.value}")

    run.cancel_requested = True
    await session.commit()

    logger.info("cancel_requested", run_id=str(run_id))
    return {"status": "cancel_requested", "run_id": str(run_id)}


@app.get("/v1/workflows", response_model=list[WorkflowResponse])
async def get_workflows() -> list[WorkflowResponse]:
    """List registered workflows and their schemas."""
    workflows = list_workflows()
    return [
        WorkflowResponse(
            name=w.name,
            description=w.description,
            steps=[{"id": s.id, "name": s.name, "description": s.description} for s in w.steps],
        )
        for w in workflows
    ]


@app.get("/healthz", response_model=HealthResponse)
async def healthz() -> HealthResponse:
    """Liveness check."""
    return HealthResponse(status="ok")


@app.get("/readyz", response_model=HealthResponse)
async def readyz() -> HealthResponse:
    """Readiness check. Fails if Postgres is unreachable.

    SQS check is best-effort locally (ElasticMQ may lag on startup).
    """
    pg_ok = False
    sqs_ok = False

    # Check Postgres (required)
    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
        pg_ok = True
    except Exception:
        pass

    # Check SQS (best-effort — ElasticMQ may not be up yet)
    try:
        boto_session = aioboto3.Session(
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            region_name=settings.aws_region,
        )
        async with boto_session.client("sqs", endpoint_url=settings.sqs_endpoint_url) as sqs:
            await sqs.get_queue_attributes(
                QueueUrl=settings.sqs_queue_url,
                AttributeNames=["ApproximateNumberOfMessages"],
            )
        sqs_ok = True
    except Exception:
        sqs_ok = True  # Don't fail readiness for SQS in local dev

    if not pg_ok:
        raise HTTPException(
            status_code=503,
            detail=f"Not ready: postgres={pg_ok}",
        )

    return HealthResponse(status="ready", postgres=pg_ok, sqs=sqs_ok)


@app.get("/metrics", response_model=MetricsResponse)
async def metrics() -> MetricsResponse:
    """Basic metrics endpoint."""
    return MetricsResponse(
        active_connections=connection_manager.total_connections,
        active_runs=connection_manager.active_runs,
    )


# --- WebSocket Endpoint ---


@app.websocket("/ws/runs/{run_id}")
async def websocket_stream(
    websocket: WebSocket,
    run_id: UUID,
    last_seq: int = Query(default=0),
) -> None:
    """Live event stream with replay-from-last_seq.

    Origin validation on handshake — WebSockets are not covered by CORS.
    """
    # Validate Origin
    origin = websocket.headers.get("origin")
    if not validate_origin(origin):
        await websocket.close(code=WS_CLOSE_UNAUTHORIZED, reason="Invalid origin")
        return

    # Verify run exists
    async with async_session_factory() as session:
        result = await session.execute(select(Run).where(Run.id == run_id))
        if result.scalar_one_or_none() is None:
            await websocket.close(code=4004, reason="Run not found")
            return

    await websocket.accept()
    await handle_websocket_stream(websocket, run_id, last_seq)


# --- Internal helpers ---


async def _enqueue_run(run_id: UUID) -> None:
    """Enqueue a run to SQS. Message body is an envelope, not the payload."""
    boto_session = aioboto3.Session(
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        region_name=settings.aws_region,
    )
    async with boto_session.client("sqs", endpoint_url=settings.sqs_endpoint_url) as sqs:
        await sqs.send_message(
            QueueUrl=settings.sqs_queue_url,
            MessageBody=json.dumps({"run_id": str(run_id), "attempt": 1}),
        )
    logger.info("run_enqueued", run_id=str(run_id))
