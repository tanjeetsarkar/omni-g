from __future__ import annotations

import asyncio
import logging
from typing import Any

from .celery_app import celery_app
from .config import get_settings
from .runtime import ProcessorRuntime

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Worker-process-level persistent runtime
# ---------------------------------------------------------------------------
# A single event loop and ProcessorRuntime are kept alive for the lifetime of
# the Celery worker process.  This avoids reconnecting to Neo4j, Redis,
# Qdrant, and the LLM client on every task invocation, keeping Kafka intake
# lightweight and analytical work contained inside persistent workers.
# ---------------------------------------------------------------------------

_worker_loop: asyncio.AbstractEventLoop | None = None
_worker_runtime: ProcessorRuntime | None = None


def _get_worker_loop() -> asyncio.AbstractEventLoop:
    """Return (or create) the persistent asyncio event loop for this worker process."""
    global _worker_loop
    if _worker_loop is None or _worker_loop.is_closed():
        _worker_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_worker_loop)
    return _worker_loop


def _get_worker_runtime() -> ProcessorRuntime:
    """Return (or initialise) the persistent ProcessorRuntime for this worker process."""
    global _worker_runtime
    if _worker_runtime is None:
        loop = _get_worker_loop()
        settings = get_settings()
        _worker_runtime = loop.run_until_complete(ProcessorRuntime.create(settings, worker_id=-1))
        logger.info("Celery worker runtime initialised")
    return _worker_runtime


@celery_app.task(  # type: ignore[misc]
    name="processor.process_event",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 3},
)
def process_event_task(self: Any, event: dict[str, Any]) -> dict[str, Any]:
    """Run one coarse Processor pipeline task for an incoming raw Kafka event.

    The runtime and its service connections are initialised once per worker
    process and reused across all task invocations.  On any exception the
    runtime is torn down so the next retry starts with fresh connections.
    """
    return _run_event(event)


def _run_event(event: dict[str, Any]) -> dict[str, Any]:
    """Core event-processing logic, separated for testability.

    Keeps the persistent runtime alive across calls and resets it on any
    failure so the next invocation gets fresh service connections.
    """
    global _worker_runtime
    loop = _get_worker_loop()
    try:
        runtime = _get_worker_runtime()
        loop.run_until_complete(runtime.process_event(event))
    except Exception:
        # Tear down the runtime on any failure so the next retry (or the next
        # task in this worker) gets a clean set of connections.
        if _worker_runtime is not None:
            try:
                loop.run_until_complete(_worker_runtime.close())
            except Exception:  # noqa: BLE001, S110
                pass
            _worker_runtime = None
        raise
    return {
        "status": "processed",
        "event_id": str(event.get("id", "")),
    }


def enqueue_process_event(event: dict[str, Any]) -> str:
    """Enqueue one coarse process_event task and return the Celery task id."""
    result = process_event_task.delay(event)  # noqa
    return str(result.id)
