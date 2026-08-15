"""Tests for the transactional outbox.

Critical test: a rolled-back transaction must publish NOTHING.
This proves the dual-write bug is absent.
"""

import pytest
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from orchestrator.db.models import Base, OutboxMessage, Run, RunState
from orchestrator.outbox.writer import write_outbox_message


@pytest.mark.integration
async def test_outbox_message_written_on_terminal_state(db_session: AsyncSession):
    """An outbox message is written when marking a run terminal."""
    run_id = uuid4()
    run = Run(id=run_id, workflow="research", input={"question": "test"})
    db_session.add(run)
    await db_session.flush()

    await write_outbox_message(db_session, run_id, "research", "succeeded")

    result = await db_session.execute(select(OutboxMessage))
    messages = list(result.scalars().all())
    assert len(messages) == 1
    assert messages[0].message_body["run_id"] == str(run_id)
    assert messages[0].message_body["state"] == "succeeded"
    assert messages[0].published is False


@pytest.mark.integration
async def test_rolled_back_transaction_publishes_nothing(database_url: str):
    """CRITICAL: A rolled-back transaction must NOT leave an outbox message.

    This is the proof that the dual-write bug is absent.
    If a run's terminal-state transaction is rolled back, no SNS publish
    should ever happen for that run.
    """
    engine = create_async_engine(database_url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    # Create a run in a committed transaction
    run_id = uuid4()
    async with session_factory() as session:
        async with session.begin():
            run = Run(id=run_id, workflow="research", input={"question": "test"})
            session.add(run)

    # Start a transaction that writes an outbox message, then ROLL IT BACK
    async with session_factory() as session:
        async with session.begin():
            await write_outbox_message(session, run_id, "research", "succeeded")
            # Force rollback
            await session.rollback()

    # Verify: no outbox messages exist for this run
    async with session_factory() as session:
        result = await session.execute(
            select(OutboxMessage).where(
                OutboxMessage.message_body["run_id"].astext == str(run_id)
            )
        )
        messages = list(result.scalars().all())
        assert len(messages) == 0, (
            "DUAL-WRITE BUG: rolled-back transaction left an outbox message!"
        )

    await engine.dispose()
