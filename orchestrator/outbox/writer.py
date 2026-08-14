"""Transactional outbox: write messages in the same transaction as state changes.

The outbox row is committed with the terminal-state transaction.
A separate relay process publishes and marks them sent.
A rolled-back transaction NEVER publishes — that's the point.
"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.config import settings
from orchestrator.db.models import OutboxMessage


async def write_outbox_message(
    session: AsyncSession,
    run_id: UUID,
    workflow: str,
    terminal_state: str,
) -> None:
    """Write an outbox message within the current transaction.

    This will only be published after the transaction commits.
    """
    msg = OutboxMessage(
        topic_arn=settings.sns_topic_arn,
        message_body={
            "run_id": str(run_id),
            "workflow": workflow,
            "state": terminal_state,
        },
        message_attributes={
            "workflow": workflow,
            "state": terminal_state,
            "run_id": str(run_id),
        },
    )
    session.add(msg)
    await session.flush()
