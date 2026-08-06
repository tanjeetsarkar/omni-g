"""Celery tasks for the Processor service (V3 Zero-Mem).

process_event_task  — coarse event dispatch from Kafka consumer
generate_briefing_task — daily audio briefing (Celery Beat)
"""

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

_worker_loop: asyncio.AbstractEventLoop | None = None
_worker_runtime: ProcessorRuntime | None = None


def _get_worker_loop() -> asyncio.AbstractEventLoop:
    global _worker_loop
    if _worker_loop is None or _worker_loop.is_closed():
        _worker_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_worker_loop)
    return _worker_loop


def _get_worker_runtime() -> ProcessorRuntime:
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
    """Run the V3 Zero-Mem pipeline for one incoming raw Kafka event."""
    return _run_event(event)


def _run_event(event: dict[str, Any]) -> dict[str, Any]:
    global _worker_runtime
    loop = _get_worker_loop()
    try:
        runtime = _get_worker_runtime()
        loop.run_until_complete(runtime.process_event(event))
    except Exception:
        if _worker_runtime is not None:
            try:
                loop.run_until_complete(_worker_runtime.close())
            except Exception:  # noqa: BLE001, S110
                pass
            _worker_runtime = None
        raise
    return {"status": "processed", "event_id": str(event.get("id", ""))}


def enqueue_process_event(event: dict[str, Any]) -> str:
    """Enqueue a process_event task and return the Celery task id."""
    result = process_event_task.delay(event)  # noqa
    return str(result.id)


# ---------------------------------------------------------------------------
# Briefing task — Celery Beat scheduled generation per tenant
# ---------------------------------------------------------------------------


async def _async_generate_briefing(tenant_id: str) -> dict[str, Any]:
    """Generate an audio briefing for *tenant_id*.

    NOTE: Briefing script content source was CommunitySummarizer (GraphRAG) in V2.
    In V3 the source will be calibrated R(q) context arrays — treat as follow-on
    work after Phase 6.  For now the script generator falls back to a placeholder.
    """
    from ..briefing.scheduler import BriefingScheduler
    from ..briefing.script_generator import BriefingScriptGenerator
    from ..briefing.storage import MinIOStorageService
    from ..briefing.tts_synthesizer import TTSSynthesizer

    settings = get_settings()
    script_gen = BriefingScriptGenerator(
        ollama_url=settings.ollama_url,
        model=settings.ollama_model,
    )
    tts = TTSSynthesizer(
        kokoro_url=settings.kokoro_url,
        elevenlabs_api_key=settings.elevenlabs_api_key,
    )
    storage = MinIOStorageService(
        endpoint_url=settings.minio_url,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        bucket=settings.minio_bucket,
    )
    scheduler = BriefingScheduler(script_gen, tts, storage)
    object_key = await scheduler.on_demand(tenant_id)
    logger.info("briefing_task_complete", extra={"tenant_id": tenant_id, "object_key": object_key})
    return {"status": "completed", "tenant_id": tenant_id, "object_key": object_key}


def _run_briefing_for_tenant(tenant_id: str) -> dict[str, Any]:
    loop = _get_worker_loop()
    return loop.run_until_complete(_async_generate_briefing(tenant_id))


@celery_app.task(  # type: ignore[misc]
    name="processor.generate_briefing",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def generate_briefing_task(self: Any, tenant_id: str) -> dict[str, Any]:
    """Generate an audio briefing for *tenant_id* (Celery Beat scheduled)."""
    return _run_briefing_for_tenant(tenant_id)


def enqueue_generate_briefing(tenant_id: str) -> str:
    result = generate_briefing_task.delay(tenant_id)  # noqa
    return str(result.id)
