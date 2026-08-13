"""Worker entry point: python -m orchestrator.worker --concurrency 4"""

import argparse
import asyncio

from orchestrator.logging import setup_logging
from orchestrator.outbox.relay import outbox_relay
from orchestrator.worker.consumer import SQSConsumer

# Ensure workflows are registered
import orchestrator.workflows.research  # noqa: F401


async def main(concurrency: int) -> None:
    setup_logging()

    consumer = SQSConsumer(concurrency=concurrency)

    # Start the outbox relay alongside the consumer
    await outbox_relay.start()

    try:
        await consumer.start()
    finally:
        await consumer.stop()
        await outbox_relay.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Orchestrator Worker")
    parser.add_argument("--concurrency", type=int, default=4, help="Max concurrent runs")
    args = parser.parse_args()

    asyncio.run(main(args.concurrency))
