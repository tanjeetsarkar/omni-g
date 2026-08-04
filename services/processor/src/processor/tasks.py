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


# ---------------------------------------------------------------------------
# Briefing task — Celery Beat scheduled generation per tenant
# ---------------------------------------------------------------------------


async def _async_generate_briefing(tenant_id: str) -> dict[str, Any]:
    """Async core of briefing generation for *tenant_id*.

    Creates all required dependencies, delegates to ``BriefingScheduler.on_demand``,
    then closes the Neo4j driver.  Imported lazily so briefing packages are not
    loaded in workers that never run briefing tasks.
    """
    from neo4j import AsyncGraphDatabase

    from ..briefing.scheduler import BriefingScheduler
    from ..briefing.script_generator import BriefingScriptGenerator
    from ..briefing.storage import MinIOStorageService
    from ..briefing.tts_synthesizer import TTSSynthesizer
    from ..graphrag.community import CommunityDetector
    from ..graphrag.indexer import GraphRAGIndexer
    from ..graphrag.summarizer import CommunitySummarizer
    from ..llm.extractor import LLMExtractor

    settings = get_settings()
    neo4j_driver = AsyncGraphDatabase.driver(
        settings.neo4j_url,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )
    try:
        community_detector = CommunityDetector(neo4j_driver)
        summarizer = CommunitySummarizer(
            neo4j_driver,
            ollama_url=settings.ollama_url,
            model=settings.ollama_model,
            openai_api_key=settings.openai_api_key,
        )
        graphrag_indexer = GraphRAGIndexer(community_detector, summarizer)
        llm_extractor = LLMExtractor()
        script_gen = BriefingScriptGenerator(graphrag_indexer, llm_extractor)
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
        scheduler = BriefingScheduler(script_gen, tts, storage, settings.briefing_hour)
        object_key = await scheduler.on_demand(tenant_id)
        logger.info(
            "briefing_task_complete",
            extra={"tenant_id": tenant_id, "object_key": object_key},
        )
        return {"status": "completed", "tenant_id": tenant_id, "object_key": object_key}
    finally:
        await neo4j_driver.close()


def _run_briefing_for_tenant(tenant_id: str) -> dict[str, Any]:
    """Synchronous wrapper for *_async_generate_briefing* — separated for testability."""
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
    """Generate an audio briefing for *tenant_id*.

    This task is dispatched by Celery Beat on a daily cron schedule when
    ``CELERY_BRIEFING_ENABLED=true``.  One task entry is registered per tenant
    listed in ``BRIEFING_TENANTS``, firing at ``BRIEFING_HOUR:00 UTC``.

    The briefing runs the full
    ``BriefingScriptGenerator → TTSSynthesizer → MinIOStorageService`` path,
    reusing the worker-process event loop.
    """
    return _run_briefing_for_tenant(tenant_id)


def enqueue_generate_briefing(tenant_id: str) -> str:
    """Enqueue a generate_briefing task for *tenant_id* and return the Celery task id."""
    result = generate_briefing_task.delay(tenant_id)  # noqa
    return str(result.id)


# ---------------------------------------------------------------------------
# Background KIQ reanalysis — V2 Step 9
# ---------------------------------------------------------------------------
# Accepts serialised CollectedEvidence records for a KIQ and runs a full
# Hypothesis-generation + ACH-scoring + Assessment-production pass outside the
# Kafka hot path.  The task is dispatched by ProcessingPipeline after the
# inline hypothesis step so Kafka intake is never blocked by LLM-heavy ACH.
# ---------------------------------------------------------------------------


async def _async_reanalyze_kiq(
    kiq_id: str,
    tenant_id: str,
    evidence_payload: list[dict[str, Any]],
) -> dict[str, Any]:
    """Async core: deserialise evidence, run ACH, produce updated Assessment."""
    # Lazy imports to avoid circular dependency: tasks → runtime → pipeline
    from ..models.entities import CollectedEvidence  # noqa: PLC0415
    from .assessment import AssessmentService  # noqa: PLC0415
    from .hypothesis import HypothesisService  # noqa: PLC0415

    evidence_list = [CollectedEvidence.model_validate(e) for e in evidence_payload]
    if not evidence_list:
        logger.info(
            "reanalyze_kiq_skipped",
            extra={"kiq_id": kiq_id, "tenant_id": tenant_id, "reason": "no_evidence"},
        )
        return {"status": "skipped", "reason": "no_evidence", "kiq_id": kiq_id}

    hypothesis_svc = HypothesisService()
    assessment_svc = AssessmentService()

    hypotheses = await hypothesis_svc.generate_candidates(kiq_id, tenant_id, evidence_list)
    leading = hypotheses[0] if hypotheses else None

    assessment_result = await assessment_svc.generate(
        kiq_id=kiq_id,
        tenant_id=tenant_id,
        evidence_list=evidence_list,
        leading_hypothesis=leading,
    )
    if assessment_result is None:
        logger.info(
            "reanalyze_kiq_no_assessment",
            extra={"kiq_id": kiq_id, "tenant_id": tenant_id},
        )
        return {"status": "skipped", "reason": "no_assessment", "kiq_id": kiq_id}

    assessment, gaps = assessment_result
    logger.info(
        "reanalyze_kiq_complete",
        extra={
            "kiq_id": kiq_id,
            "tenant_id": tenant_id,
            "hypotheses_count": len(hypotheses),
            "assessment_id": assessment.id,
            "hypothesis_id": assessment.hypothesis_id,
            "gaps_count": len(gaps),
        },
    )
    return {
        "status": "completed",
        "kiq_id": kiq_id,
        "assessment_id": assessment.id,
        "hypotheses_count": len(hypotheses),
        "gaps_count": len(gaps),
    }


def _run_reanalyze_kiq(
    kiq_id: str,
    tenant_id: str,
    evidence_payload: list[dict[str, Any]],
) -> dict[str, Any]:
    """Synchronous wrapper for *_async_reanalyze_kiq* — separated for testability."""
    loop = _get_worker_loop()
    return loop.run_until_complete(_async_reanalyze_kiq(kiq_id, tenant_id, evidence_payload))


@celery_app.task(  # type: ignore[misc]
    name="processor.reanalyze_kiq",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 2},
)
def reanalyze_kiq_task(
    self: Any,
    kiq_id: str,
    tenant_id: str,
    evidence_payload: list[dict[str, Any]],
) -> dict[str, Any]:
    """Background ACH reanalysis for a KIQ.

    Accepts serialised :class:`~src.models.entities.CollectedEvidence` records
    and runs hypothesis generation, ACH scoring, and Assessment production
    outside the Kafka hot path.  Dispatched by
    :class:`~src.processor.pipeline.ProcessingPipeline` immediately after the
    inline hypothesis-generation step so Kafka intake is never blocked by
    LLM-heavy ACH scoring.
    """
    return _run_reanalyze_kiq(kiq_id, tenant_id, evidence_payload)


def enqueue_reanalyze_kiq(
    kiq_id: str,
    tenant_id: str,
    evidence_payload: list[dict[str, Any]],
) -> str:
    """Enqueue a reanalyze_kiq task and return the Celery task id."""
    result = reanalyze_kiq_task.delay(kiq_id, tenant_id, evidence_payload)  # noqa
    return str(result.id)
