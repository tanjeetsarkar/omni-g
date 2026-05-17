from __future__ import annotations

import asyncio
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
    from ..kafka.consumer import RawEventConsumer
    from ..llm.extractor import LLMExtractor
    from ..resolution.resolver import EntityResolver
    from .pipeline import ProcessingPipeline

    consumer = RawEventConsumer(
        brokers=cfg.kafka_brokers,
        topic=cfg.kafka_raw_topic,
        group_id=cfg.kafka_group_id,
        dlq_topic=cfg.kafka_dlq_topic,
    )
    deduplicator = ContentDeduplicator(ttl_seconds=cfg.dedup_ttl_seconds)
    await deduplicator.connect(cfg.redis_url)
    extractor = LLMExtractor()

    neo4j_driver = AsyncGraphDatabase.driver(
        cfg.neo4j_url,
        auth=(cfg.neo4j_user, cfg.neo4j_password),
    )
    qdrant_client = AsyncQdrantClient(
        url=cfg.qdrant_url,
        api_key=cfg.qdrant_api_key,
    )
    resolver = EntityResolver(neo4j_driver=neo4j_driver, qdrant_client=qdrant_client)

    pipeline = ProcessingPipeline(
        deduplicator=deduplicator,
        extractor=extractor,
        resolver=resolver,
    )
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
        await pipeline.process(event)

    try:
        await consumer.process_messages(_handle)
    finally:
        await neo4j_driver.close()
        await qdrant_client.close()
        logger.info(
            "Kafka consumer worker shut down; connections closed",
            extra={"worker_id": worker_id},
        )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    logger.info("Processor service starting", extra={"port": settings.http_port})

    consumer_tasks: list[asyncio.Task[None]] = []
    if settings.kafka_enabled:
        for worker_id in range(settings.kafka_num_workers):
            try:
                task = asyncio.create_task(startup_consumer(settings, worker_id=worker_id))
                consumer_tasks.append(task)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Failed to create Kafka consumer task %d: %s", worker_id, exc
                )

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
            return JSONResponse(
                status_code=422,
                content={"valid": False, "errors": errors},
            )

        return JSONResponse({"valid": True})

    return app


app = create_app()

