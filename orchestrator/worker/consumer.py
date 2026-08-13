"""SQS consumer: receives messages, manages visibility heartbeat, dispatches work.

Key behaviors:
- Long polling (WaitTimeSeconds=20)
- Visibility-timeout heartbeat: extends while work is in progress
- Fence acquisition before executing
- Message deletion only after successful step completion
- At-least-once delivery is safe because of fencing + step idempotency
"""

import asyncio
import json
import signal
import uuid as uuid_mod
from typing import Any

import aioboto3
import structlog

from orchestrator.config import settings
from orchestrator.worker.executor import execute_run

logger = structlog.get_logger()


class SQSConsumer:
    """Consumes SQS messages and dispatches run execution."""

    def __init__(self, concurrency: int = 4) -> None:
        self._concurrency = concurrency
        self._running = False
        self._worker_id = f"worker-{uuid_mod.uuid4().hex[:8]}"
        self._tasks: set[asyncio.Task[Any]] = set()
        self._semaphore = asyncio.Semaphore(concurrency)

    async def start(self) -> None:
        """Start consuming messages."""
        self._running = True
        logger.info(
            "sqs_consumer_started",
            worker_id=self._worker_id,
            concurrency=self._concurrency,
        )

        # Handle graceful shutdown
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._handle_shutdown)

        await self._consume_loop()

    def _handle_shutdown(self) -> None:
        """Handle graceful shutdown signal."""
        logger.info("shutdown_requested", worker_id=self._worker_id)
        self._running = False

    async def stop(self) -> None:
        """Stop consuming and wait for in-flight work."""
        self._running = False
        if self._tasks:
            logger.info("waiting_for_inflight", count=len(self._tasks))
            await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _consume_loop(self) -> None:
        """Main consumption loop with long polling."""
        boto_session = aioboto3.Session(
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            region_name=settings.aws_region,
        )

        async with boto_session.client(
            "sqs",
            endpoint_url=settings.sqs_endpoint_url,
        ) as sqs_client:
            while self._running:
                try:
                    response = await sqs_client.receive_message(
                        QueueUrl=settings.sqs_queue_url,
                        MaxNumberOfMessages=min(self._concurrency, 10),
                        WaitTimeSeconds=20,
                        VisibilityTimeout=60,
                        MessageAttributeNames=["All"],
                    )

                    messages = response.get("Messages", [])
                    for msg in messages:
                        await self._semaphore.acquire()
                        task = asyncio.create_task(
                            self._process_message(sqs_client, msg)
                        )
                        self._tasks.add(task)
                        task.add_done_callback(self._task_done)

                except asyncio.CancelledError:
                    return
                except Exception:
                    logger.exception("consume_error")
                    await asyncio.sleep(2.0)

    def _task_done(self, task: asyncio.Task[Any]) -> None:
        """Clean up completed task."""
        self._tasks.discard(task)
        self._semaphore.release()

    async def _process_message(self, sqs_client: Any, message: dict[str, Any]) -> None:
        """Process a single SQS message with visibility heartbeat."""
        receipt_handle = message["ReceiptHandle"]
        body = json.loads(message["Body"])
        run_id = body["run_id"]
        attempt = body.get("attempt", 1)

        log = logger.bind(run_id=run_id, attempt=attempt, worker_id=self._worker_id)
        log.info("message_received")

        # Start visibility heartbeat
        heartbeat_task = asyncio.create_task(
            self._visibility_heartbeat(sqs_client, receipt_handle, run_id)
        )

        try:
            success = await execute_run(
                run_id=uuid_mod.UUID(run_id),
                worker_id=self._worker_id,
                attempt=attempt,
            )

            if success:
                # Delete message only on success
                await sqs_client.delete_message(
                    QueueUrl=settings.sqs_queue_url,
                    ReceiptHandle=receipt_handle,
                )
                log.info("message_deleted")
            else:
                log.warning("execution_failed_will_retry")

        except Exception:
            log.exception("message_processing_failed")
        finally:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass

    async def _visibility_heartbeat(
        self,
        sqs_client: Any,
        receipt_handle: str,
        run_id: str,
    ) -> None:
        """Extend visibility timeout while work is in progress.

        Short visibility (~60s) + heartbeat extension every 30s.
        Stop extending on completion or lease loss.
        """
        while True:
            try:
                await asyncio.sleep(30)
                await sqs_client.change_message_visibility(
                    QueueUrl=settings.sqs_queue_url,
                    ReceiptHandle=receipt_handle,
                    VisibilityTimeout=60,
                )
                logger.debug("visibility_extended", run_id=run_id)
            except asyncio.CancelledError:
                return
            except Exception:
                logger.warning("visibility_extension_failed", run_id=run_id)
                return
