from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, field_validator

from .config import Settings, get_settings

logger = logging.getLogger(__name__)


_LOG_RECORD_KEYS = {
    "name",
    "msg",
    "args",
    "levelname",
    "levelno",
    "pathname",
    "filename",
    "module",
    "exc_info",
    "exc_text",
    "stack_info",
    "lineno",
    "funcName",
    "created",
    "msecs",
    "relativeCreated",
    "thread",
    "threadName",
    "processName",
    "process",
    "message",
    "asctime",
}


class StructuredFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        message = super().format(record)
        extra = {
            key: value for key, value in record.__dict__.items() if key not in _LOG_RECORD_KEYS
        }
        if not extra:
            return message
        return f"{message} | extra={json.dumps(extra, default=str, ensure_ascii=False)}"


def configure_logging(level_name: str) -> None:
    level = getattr(logging, level_name.upper(), logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(StructuredFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logging.basicConfig(level=level, handlers=[handler], force=True)

    # Keep first-party pipeline logs visible while suppressing very noisy
    # client-internal debug output from Kafka and transport libraries.
    for name in (
        "src.processor",
        "src.kafka",
        "src.llm",
        "src.dedup",
        "src.graph",
        "src.graphrag",
        "src.resolution",
        "src.briefing",
    ):
        logging.getLogger(name).setLevel(level)

    for noisy_logger in (
        "kafka",
        "kafka.client",
        "kafka.conn",
        "kafka.consumer",
        "kafka.consumer.fetcher",
        "urllib3",
    ):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)


async def startup_briefing_storage_preflight(cfg: Settings) -> None:
    """Ensure briefing storage bucket exists before serving briefing endpoints."""
    from ..briefing.storage import MinIOStorageService

    logger.info("Briefing storage preflight starting")
    storage = MinIOStorageService(
        endpoint_url=cfg.minio_url,
        access_key=cfg.minio_access_key,
        secret_key=cfg.minio_secret_key,
        bucket=cfg.minio_bucket,
    )
    await storage.ensure_bucket()
    logger.info(
        "Briefing storage preflight complete",
        extra={"minio_url": cfg.minio_url, "minio_bucket": cfg.minio_bucket},
    )


async def startup_consumer(cfg: Settings, worker_id: int = 0) -> None:
    """Start one Kafka consumer worker in the processing pipeline.

    Multiple workers (``KAFKA_NUM_WORKERS``) are launched by the lifespan
    handler.  Each worker creates its own :class:`RawEventConsumer` connection
    inside the same consumer group so Kafka rebalances partition ownership
    automatically.
    """
    from neo4j import AsyncGraphDatabase
    from qdrant_client import AsyncQdrantClient

    from ..dedup.deduplicator import ContentDeduplicator
    from ..graph.persistence import GraphPersistenceService
    from ..graph.schema import GraphSchemaManager
    from ..graphrag.community import CommunityDetector
    from ..graphrag.indexer import GraphRAGIndexer
    from ..graphrag.summarizer import CommunitySummarizer
    from ..kafka.consumer import RawEventConsumer
    from ..llm.extractor import LLMExtractor
    from ..resolution.resolver import EntityResolver
    from .alert_publisher import AlertPublisher
    from .pipeline import ProcessingPipeline
    from .stage_publisher import StageEventPublisher

    logger.info(
        "Initialising processor worker dependencies",
        extra={
            "worker_id": worker_id,
            "kafka_raw_topic": cfg.kafka_raw_topic,
            "kafka_dlq_topic": cfg.kafka_dlq_topic,
            "kafka_alerts_topic": cfg.kafka_alerts_topic,
            "kafka_processor_events_topic": cfg.kafka_processor_events_topic,
            "redis_url": cfg.redis_url,
            "neo4j_url": cfg.neo4j_url,
            "qdrant_url": cfg.qdrant_url,
        },
    )

    consumer = RawEventConsumer(
        brokers=cfg.kafka_brokers,
        topic=cfg.kafka_raw_topic,
        group_id=cfg.kafka_group_id,
        dlq_topic=cfg.kafka_dlq_topic,
    )
    logger.info("RawEventConsumer initialised", extra={"worker_id": worker_id})
    deduplicator = ContentDeduplicator(ttl_seconds=cfg.dedup_ttl_seconds)
    await deduplicator.connect(cfg.redis_url)
    logger.info("Deduplicator connected", extra={"worker_id": worker_id})
    extractor = LLMExtractor()
    logger.info("LLM extractor initialised", extra={"worker_id": worker_id})

    neo4j_driver = AsyncGraphDatabase.driver(
        cfg.neo4j_url,
        auth=(cfg.neo4j_user, cfg.neo4j_password),
    )
    qdrant_client = AsyncQdrantClient(
        url=cfg.qdrant_url,
        api_key=cfg.qdrant_api_key,
    )
    resolver = EntityResolver(neo4j_driver=neo4j_driver, qdrant_client=qdrant_client)
    logger.info("EntityResolver initialised", extra={"worker_id": worker_id})

    # M4.2: Neo4j schema + persistence
    schema_manager = GraphSchemaManager(neo4j_driver)
    try:
        await schema_manager.initialize()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Graph schema initialization failed (continuing)",
            extra={"error": str(exc), "worker_id": worker_id},
        )
    graph_persistence = GraphPersistenceService(neo4j_driver)
    logger.info("GraphPersistenceService initialised", extra={"worker_id": worker_id})

    # M4.3: GraphRAG indexing
    community_detector = CommunityDetector(neo4j_driver)
    summarizer = CommunitySummarizer(
        neo4j_driver,
        ollama_url=cfg.ollama_url,
        model=cfg.ollama_model,
        openai_api_key=cfg.openai_api_key,
    )
    graphrag_indexer = GraphRAGIndexer(community_detector, summarizer)
    logger.info("GraphRAG indexer initialised", extra={"worker_id": worker_id})

    alert_publisher = AlertPublisher(
        brokers=cfg.kafka_brokers,
        topic=cfg.kafka_alerts_topic,
    )
    logger.info("AlertPublisher initialised", extra={"worker_id": worker_id})

    stage_publisher = StageEventPublisher(
        brokers=cfg.kafka_brokers,
        topic=cfg.kafka_processor_events_topic,
    )
    logger.info("StageEventPublisher initialised", extra={"worker_id": worker_id})

    pipeline = ProcessingPipeline(
        deduplicator=deduplicator,
        extractor=extractor,
        resolver=resolver,
        graph_persistence=graph_persistence,
        graphrag_indexer=graphrag_indexer,
        alert_publisher=alert_publisher,
        stage_publisher=stage_publisher,
    )
    logger.info("ProcessingPipeline initialised", extra={"worker_id": worker_id})
    consumer.start()

    logger.info(
        "Entity resolver initialised",
        extra={
            "worker_id": worker_id,
            "neo4j_url": cfg.neo4j_url,
            "qdrant_url": cfg.qdrant_url,
        },
    )

    logger.info(
        "Kafka consumer worker started",
        extra={"worker_id": worker_id, "topic": cfg.kafka_raw_topic},
    )

    async def _handle(event: dict[str, Any]) -> None:
        logger.debug(
            "Kafka event payload received by worker",
            extra={"worker_id": worker_id, "event_payload": event},
        )
        await pipeline.process(event)

    try:
        await consumer.process_messages(_handle)
    finally:
        await neo4j_driver.close()
        await qdrant_client.close()
        alert_publisher.close()
        stage_publisher.close()
        logger.info(
            "Kafka consumer worker shut down; connections closed",
            extra={"worker_id": worker_id},
        )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    configure_logging(settings.log_level)
    logger.info("Processor service starting", extra={"port": settings.http_port})
    logger.info(
        "Processor runtime configuration loaded",
        extra={
            "log_level": settings.log_level,
            "kafka_enabled": settings.kafka_enabled,
            "kafka_brokers": settings.kafka_brokers,
            "kafka_raw_topic": settings.kafka_raw_topic,
            "kafka_num_workers": settings.kafka_num_workers,
            "neo4j_url": settings.neo4j_url,
            "qdrant_url": settings.qdrant_url,
            "ollama_url": settings.ollama_url,
            "ollama_model": settings.ollama_model,
            "briefing_preflight_enabled": settings.briefing_preflight_enabled,
            "briefing_preflight_strict": settings.briefing_preflight_strict,
        },
    )

    if settings.briefing_preflight_enabled:
        try:
            await startup_briefing_storage_preflight(settings)
        except Exception as exc:  # noqa: BLE001
            if settings.briefing_preflight_strict:
                logger.error("Briefing storage preflight failed (strict mode): %s", exc)
                raise
            logger.warning("Briefing storage preflight failed (continuing): %s", exc)

    consumer_tasks: list[asyncio.Task[None]] = []
    if settings.kafka_enabled:
        logger.info("Kafka processing enabled; launching workers")
        for worker_id in range(settings.kafka_num_workers):
            try:
                task = asyncio.create_task(startup_consumer(settings, worker_id=worker_id))
                consumer_tasks.append(task)
                logger.info("Kafka consumer worker task launched", extra={"worker_id": worker_id})
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to create Kafka consumer task %d: %s", worker_id, exc)
    else:
        logger.info("Kafka processing disabled; worker startup skipped")

    yield

    for task in consumer_tasks:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    logger.info("Processor service shutting down")


class ValidationError(BaseModel):
    field: str
    message: str


class ValidateRequest(BaseModel):
    """Payload received from the Aggregator validation sidecar."""

    source: str
    payload: dict[str, Any]

    @field_validator("source")
    @classmethod
    def source_must_be_http_url(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("source must not be blank")
        parsed = urlparse(v)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("source must be a valid HTTP URL")
        return v


class ValidateResponse(BaseModel):
    valid: bool
    errors: list[ValidationError] = []


def create_app(settings: Settings | None = None) -> FastAPI:
    if settings is None:
        settings = get_settings()

    app = FastAPI(
        title="Omni-G Processor",
        description="LLM entity extraction, graph persistence, and GraphRAG indexing service",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = settings

    @app.get("/metrics", tags=["ops"])
    def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/health", tags=["ops"])
    async def health() -> JSONResponse:
        return JSONResponse({"status": "ok", "service": "processor"})

    @app.get("/ready", tags=["ops"])
    async def ready() -> JSONResponse:
        return JSONResponse({"status": "ready", "service": "processor"})

    @app.post("/validate", tags=["ops"], response_model=ValidateResponse)
    async def validate(body: ValidateRequest) -> JSONResponse:
        """Schema validation sidecar endpoint called by the Aggregator.

        Validates that the event envelope has a valid URL source, a non-empty
        payload dict, no None/empty-string top-level values, and at least one
        recognised content key (text, content, data, url).
        """
        errors: list[dict[str, str]] = []

        logger.info("Validation request received", extra={"source": body.source})
        logger.debug("Validation request payload", extra={"body": body.model_dump()})

        if not body.source:
            errors.append({"field": "source", "message": "field 'source' is required"})

        if body.payload is None:
            errors.append({"field": "payload", "message": "field 'payload' is required"})
        elif not body.payload:
            errors.append({"field": "payload", "message": "payload must not be empty"})
        else:
            # Reject top-level keys whose value is None or empty string.
            for k, v in body.payload.items():
                if v is None or v == "":
                    errors.append(
                        {
                            "field": f"payload.{k}",
                            "message": "value must not be None or empty string",
                        }
                    )

            # Require at least one recognised content key.
            required_keys = {"text", "content", "data", "url"}
            if not required_keys.intersection(body.payload.keys()):
                errors.append(
                    {
                        "field": "payload",
                        "message": "must contain at least one of: text, content, data, url",
                    }
                )

        if errors:
            logger.info(
                "Validation request failed",
                extra={"source": body.source, "error_count": len(errors), "errors": errors},
            )
            return JSONResponse(
                status_code=422,
                content={"valid": False, "errors": errors},
            )

        logger.info("Validation request succeeded", extra={"source": body.source})
        return JSONResponse({"valid": True})

    @app.get("/briefings", tags=["briefings"])
    async def list_briefings() -> JSONResponse:
        """Return signed URLs for the latest briefing audio for all configured tenants."""
        from ..briefing.storage import MinIOStorageService
        from ..briefing.url_signer import BriefingURLSigner

        cfg: Settings = app.state.settings
        logger.info("Listing latest briefings for configured tenants")
        storage = MinIOStorageService(
            endpoint_url=cfg.minio_url,
            access_key=cfg.minio_access_key,
            secret_key=cfg.minio_secret_key,
            bucket=cfg.minio_bucket,
        )
        signer = BriefingURLSigner(storage)
        tenant_ids = [t.strip() for t in cfg.briefing_tenants.split(",") if t.strip()]
        results = []
        for tenant_id in tenant_ids:
            signed_url = await signer.sign_latest(tenant_id)
            if signed_url is not None:
                # Extract object key from the signed URL path
                from urllib.parse import urlparse as _urlparse

                parsed = _urlparse(signed_url)
                object_key = parsed.path.lstrip("/")
                results.append(
                    {"tenant_id": tenant_id, "object_key": object_key, "signed_url": signed_url}
                )
            logger.debug("Briefings list response payload", extra={"results": results})
        return JSONResponse(results)

    @app.post("/briefings/generate", tags=["briefings"])
    async def generate_briefing(body: dict[str, str]) -> JSONResponse:
        """Trigger an on-demand audio briefing for a tenant.

        Request body: ``{"tenant_id": "<tenant>"}``
        Returns: ``{"signed_url": "<presigned-url>"}``
        """
        from ..briefing.scheduler import BriefingScheduler
        from ..briefing.script_generator import BriefingScriptGenerator
        from ..briefing.storage import MinIOStorageService
        from ..briefing.tts_synthesizer import TTSSynthesizer
        from ..graphrag.community import CommunityDetector
        from ..graphrag.indexer import GraphRAGIndexer
        from ..graphrag.summarizer import CommunitySummarizer
        from ..llm.extractor import LLMExtractor

        cfg: Settings = app.state.settings
        tenant_id = body.get("tenant_id", "default")
        logger.info("On-demand briefing generation requested", extra={"tenant_id": tenant_id})
        logger.debug("On-demand briefing request payload", extra={"body": body})

        from neo4j import AsyncGraphDatabase

        neo4j_driver = AsyncGraphDatabase.driver(
            cfg.neo4j_url, auth=(cfg.neo4j_user, cfg.neo4j_password)
        )

        try:
            community_detector = CommunityDetector(neo4j_driver)
            summarizer = CommunitySummarizer(
                neo4j_driver,
                ollama_url=cfg.ollama_url,
                model=cfg.ollama_model,
                openai_api_key=cfg.openai_api_key,
            )
            graphrag_indexer = GraphRAGIndexer(community_detector, summarizer)
            llm_extractor = LLMExtractor()
            script_gen = BriefingScriptGenerator(graphrag_indexer, llm_extractor)
            tts = TTSSynthesizer(
                kokoro_url=cfg.kokoro_url,
                elevenlabs_api_key=cfg.elevenlabs_api_key,
            )
            storage = MinIOStorageService(
                endpoint_url=cfg.minio_url,
                access_key=cfg.minio_access_key,
                secret_key=cfg.minio_secret_key,
                bucket=cfg.minio_bucket,
            )
            scheduler = BriefingScheduler(script_gen, tts, storage, cfg.briefing_hour)
            object_key = await scheduler.on_demand(tenant_id)
            signed_url = await storage.get_signed_url(object_key)
            logger.info(
                "On-demand briefing generated",
                extra={"tenant_id": tenant_id, "object_key": object_key},
            )
            logger.debug(
                "On-demand briefing response payload",
                extra={"tenant_id": tenant_id, "signed_url": signed_url},
            )
        finally:
            await neo4j_driver.close()

        return JSONResponse({"signed_url": signed_url})

    return app


app = create_app()
