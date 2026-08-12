"""SQLAlchemy ORM models matching SPEC section 4."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class RunState(str, enum.Enum):
    queued = "queued"
    running = "running"
    waiting = "waiting"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


class StepState(str, enum.Enum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    skipped = "skipped"


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workflow: Mapped[str] = mapped_column(Text, nullable=False)
    input: Mapped[dict] = mapped_column(JSONB, nullable=False)
    state: Mapped[RunState] = mapped_column(
        Enum(RunState, name="run_state", create_constraint=True),
        nullable=False,
        default=RunState.queued,
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    owner_worker: Mapped[str | None] = mapped_column(Text, nullable=True)
    lease_expires: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fence: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("idempotency_key", name="runs_idem"),
        Index("ix_runs_state", "state"),
    )


class Step(Base):
    __tablename__ = "steps"

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True
    )
    step_id: Mapped[str] = mapped_column(Text, primary_key=True)
    state: Mapped[StepState] = mapped_column(
        Enum(StepState, name="step_state", create_constraint=True),
        nullable=False,
        default=StepState.pending,
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    input: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    output: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Checkpoint(Base):
    __tablename__ = "checkpoints"

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True
    )
    seq: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    after_step: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[dict] = mapped_column(JSONB, nullable=False)
    fence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Event(Base):
    __tablename__ = "events"

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True
    )
    seq: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_events_run_seq", "run_id", "seq"),
    )


class OutboxMessage(Base):
    """Transactional outbox for SNS publishing."""

    __tablename__ = "outbox"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    topic_arn: Mapped[str] = mapped_column(Text, nullable=False)
    message_body: Mapped[dict] = mapped_column(JSONB, nullable=False)
    message_attributes: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    published: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_outbox_unpublished", "published", "created_at", postgresql_where="NOT published"),
    )
