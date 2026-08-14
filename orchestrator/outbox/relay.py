"""Outbox relay: publish outbox messages to SNS and mark them sent.

Runs as a background task in the worker process. Polls the outbox table
for unpublished messages and publishes them to SNS.
"""

import asyncio
import json
from datetime import datetime, timezone

import aioboto3
import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.config import settings
from orchestrator.db.engine import async_session_factory
from orchestrator.db.models import OutboxMessage

logger = structlog.get_logger()


class OutboxRelay:
    """Publishes outbox messages to SNS."""

    def __init__(self) -> None:
        self._running = False
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Start the relay loop."""
        self._running = True
        self._task = asyncio.create_task(self._relay_loop())
        logger.info("outbox_relay_started")

    async def stop(self) -> None:
        """Stop the relay loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("outbox_relay_stopped")

    async def _relay_loop(self) -> None:
        """Poll for unpublished messages and publish them."""
        while self._running:
            try:
                await self._publish_batch()
                await asyncio.sleep(0.5)  # Poll every 500ms
            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("outbox_relay_error")
                await asyncio.sleep(2.0)

    async def _publish_batch(self) -> None:
        """Fetch and publish a batch of unpublished outbox messages.

        Gracefully handles SNS being unavailable (e.g., LocalStack not running).
        Messages stay in the outbox and will be retried when SNS is available.
        """
        async with async_session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    select(OutboxMessage)
                    .where(OutboxMessage.published == False)  # noqa: E712
                    .order_by(OutboxMessage.created_at)
                    .limit(10)
                    .with_for_update(skip_locked=True)
                )
                messages = list(result.scalars().all())

                if not messages:
                    return

                try:
                    boto_session = aioboto3.Session(
                        aws_access_key_id=settings.aws_access_key_id,
                        aws_secret_access_key=settings.aws_secret_access_key,
                        region_name=settings.aws_region,
                    )

                    async with boto_session.client(
                        "sns",
                        endpoint_url=settings.sns_endpoint_url,
                    ) as sns_client:
                        for msg in messages:
                            try:
                                # Build SNS message attributes
                                sns_attrs = {}
                                for key, value in msg.message_attributes.items():
                                    sns_attrs[key] = {
                                        "DataType": "String",
                                        "StringValue": str(value),
                                    }

                                await sns_client.publish(
                                    TopicArn=msg.topic_arn,
                                    Message=json.dumps(msg.message_body),
                                    MessageAttributes=sns_attrs,
                                )

                                # Mark as published
                                await session.execute(
                                    update(OutboxMessage)
                                    .where(OutboxMessage.id == msg.id)
                                    .values(
                                        published=True,
                                        published_at=datetime.now(timezone.utc),
                                    )
                                )

                                logger.info(
                                    "outbox_message_published",
                                    outbox_id=msg.id,
                                    topic_arn=msg.topic_arn,
                                    run_id=msg.message_body.get("run_id"),
                                )
                            except Exception:
                                logger.exception(
                                    "outbox_publish_failed",
                                    outbox_id=msg.id,
                                )
                                break
                except Exception:
                    # SNS not available (LocalStack not running) — skip silently
                    # Messages stay in outbox for retry when SNS comes up
                    pass


# Singleton
outbox_relay = OutboxRelay()
