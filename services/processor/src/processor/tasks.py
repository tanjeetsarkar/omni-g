from __future__ import annotations

import asyncio
import logging
from typing import Any

from .celery_app import celery_app
from .config import get_settings
from .runtime import ProcessorRuntime

logger = logging.getLogger(__name__)


@celery_app.task(
    name="processor.process_event",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 3},
)
def process_event_task(self: Any, event: dict[str, Any]) -> dict[str, Any]:
    """Run one coarse Processor pipeline task for an incoming raw Kafka event."""
    return asyncio.run(_process_event(event))


def enqueue_process_event(event: dict[str, Any]) -> str:
    """Enqueue one coarse process_event task and return the Celery task id."""
    result = process_event_task.delay(event)
    return str(result.id)


async def _process_event(event: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    runtime = await ProcessorRuntime.create(settings, worker_id=-1)
    try:
        await runtime.process_event(event)
    finally:
        await runtime.close()

    return {
        "status": "processed",
        "event_id": str(event.get("id", "")),
    }
