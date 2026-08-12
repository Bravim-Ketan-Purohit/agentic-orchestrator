"""Initial schema: runs, steps, checkpoints, events, outbox.

Revision ID: 001
Revises: None
Create Date: 2026-08-17
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create enums using raw SQL with IF NOT EXISTS
    op.execute("DO $$ BEGIN CREATE TYPE run_state AS ENUM ('queued','running','waiting','succeeded','failed','cancelled'); EXCEPTION WHEN duplicate_object THEN null; END $$;")
    op.execute("DO $$ BEGIN CREATE TYPE step_state AS ENUM ('pending','running','succeeded','failed','skipped'); EXCEPTION WHEN duplicate_object THEN null; END $$;")

    # runs
    op.execute("""
        CREATE TABLE IF NOT EXISTS runs (
            id UUID PRIMARY KEY,
            workflow TEXT NOT NULL,
            input JSONB NOT NULL,
            state run_state NOT NULL DEFAULT 'queued',
            attempt INTEGER NOT NULL DEFAULT 0,
            owner_worker TEXT,
            lease_expires TIMESTAMPTZ,
            fence BIGINT NOT NULL DEFAULT 0,
            idempotency_key TEXT,
            cancel_requested BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS runs_idem ON runs (idempotency_key) WHERE idempotency_key IS NOT NULL")
    op.execute("CREATE INDEX IF NOT EXISTS ix_runs_state ON runs (state)")

    # steps
    op.execute("""
        CREATE TABLE IF NOT EXISTS steps (
            run_id UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
            step_id TEXT NOT NULL,
            state step_state NOT NULL DEFAULT 'pending',
            attempt INTEGER NOT NULL DEFAULT 0,
            input JSONB,
            output JSONB,
            error JSONB,
            started_at TIMESTAMPTZ,
            finished_at TIMESTAMPTZ,
            PRIMARY KEY (run_id, step_id)
        )
    """)

    # checkpoints
    op.execute("""
        CREATE TABLE IF NOT EXISTS checkpoints (
            run_id UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
            seq BIGINT NOT NULL,
            after_step TEXT NOT NULL,
            state JSONB NOT NULL,
            fence BIGINT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (run_id, seq)
        )
    """)

    # events (append-only, gap-free per run)
    op.execute("""
        CREATE TABLE IF NOT EXISTS events (
            run_id UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
            seq BIGINT NOT NULL,
            kind TEXT NOT NULL,
            payload JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (run_id, seq)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_events_run_seq ON events (run_id, seq)")

    # outbox (transactional outbox for SNS)
    op.execute("""
        CREATE TABLE IF NOT EXISTS outbox (
            id BIGSERIAL PRIMARY KEY,
            topic_arn TEXT NOT NULL,
            message_body JSONB NOT NULL,
            message_attributes JSONB NOT NULL DEFAULT '{}',
            published BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            published_at TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_outbox_unpublished ON outbox (published, created_at) WHERE NOT published")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS outbox")
    op.execute("DROP TABLE IF EXISTS events")
    op.execute("DROP TABLE IF EXISTS checkpoints")
    op.execute("DROP TABLE IF EXISTS steps")
    op.execute("DROP TABLE IF EXISTS runs")
    op.execute("DROP TYPE IF EXISTS step_state")
    op.execute("DROP TYPE IF EXISTS run_state")
