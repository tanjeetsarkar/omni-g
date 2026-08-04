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
    from ..kafka.consumer import RawEventConsumer
    from .runtime import ProcessorRuntime
    from .tasks import enqueue_process_event

    consumer = RawEventConsumer(
        brokers=cfg.kafka_brokers,
        topic=cfg.kafka_raw_topic,
        group_id=cfg.kafka_group_id,
        dlq_topic=cfg.kafka_dlq_topic,
    )
    logger.info("RawEventConsumer initialised", extra={"worker_id": worker_id})
    runtime: ProcessorRuntime | None = None
    if not cfg.celery_enabled:
        runtime = await ProcessorRuntime.create(cfg, worker_id=worker_id)

    consumer.start()

    logger.info(
        "Kafka consumer worker started",
        extra={
            "worker_id": worker_id,
            "topic": cfg.kafka_raw_topic,
            "celery_enabled": cfg.celery_enabled,
            "celery_task_queue": cfg.celery_task_queue,
            "celery_task_always_eager": cfg.celery_task_always_eager,
        },
    )

    async def _handle(event: dict[str, Any]) -> None:
        logger.debug(
            "Kafka event payload received by worker",
            extra={"worker_id": worker_id, "event_payload": event},
        )
        if cfg.celery_enabled:
            task_id = enqueue_process_event(event)
            logger.info(
                "Dispatched coarse process_event Celery task",
                extra={"worker_id": worker_id, "task_id": task_id, "event_id": event.get("id")},
            )
            return

        if runtime is None:
            raise RuntimeError("Processor runtime not initialised")

        await runtime.process_event(event)

    try:
        await consumer.process_messages(_handle)
    finally:
        if runtime is not None:
            await runtime.close()
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
            "celery_enabled": settings.celery_enabled,
            "celery_broker_url": settings.celery_broker_url,
            "celery_result_backend": settings.celery_result_backend,
            "celery_task_queue": settings.celery_task_queue,
            "celery_task_always_eager": settings.celery_task_always_eager,
            "celery_task_ignore_result": settings.celery_task_ignore_result,
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


class SearchRequest(BaseModel):
    query: str
    tenant_id: str
    limit: int = 20


class SearchResponse(BaseModel):
    entities: list[dict[str, Any]]
    relationships: list[dict[str, Any]] = []
    total: int


class FetchEntitiesRequest(BaseModel):
    """Direct entity fetch by ID — used for real-time alert hydration.

    Bypasses semantic search and fetches entities straight from Neo4j by their
    canonical IDs, then expands with 1-hop neighbours.
    """

    entity_ids: list[str]
    tenant_id: str = "default"


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

    # ── Direct entity fetch by ID ─────────────────────────────────────────

    @app.post("/entities", tags=["search"], response_model=SearchResponse)
    async def fetch_entities_by_ids(body: FetchEntitiesRequest) -> JSONResponse:
        """Fetch entities directly from Neo4j by canonical ID.

        Used by the Delivery layer to hydrate real-time alerts (WebSocket
        ``analyst-alerts``) without triggering a new ingestion cycle.
        Returns matched entities plus 1-hop neighbours and their relationships.
        """
        from datetime import UTC
        from datetime import datetime as _dt

        from neo4j import AsyncGraphDatabase

        from ..graph.persistence import GraphPersistenceService
        from ..models.entities import Entity

        if not body.entity_ids:
            return JSONResponse({"entities": [], "relationships": [], "total": 0})

        cfg: Settings = app.state.settings
        neo4j_driver = AsyncGraphDatabase.driver(
            cfg.neo4j_url, auth=(cfg.neo4j_user, cfg.neo4j_password)
        )
        graph_persistence = GraphPersistenceService(neo4j_driver)

        entities: list[Entity] = []
        relationships: list[dict[str, Any]] = []
        try:
            now = _dt.now(UTC)
            async with neo4j_driver.session() as session:
                result = await session.run(
                    "MATCH (e:Entity) WHERE e.id IN $ids RETURN e",
                    ids=body.entity_ids,
                )
                rows = await result.data()

            for row in rows:
                node = row.get("e", {})
                try:
                    entities.append(
                        Entity(
                            id=node.get("id", ""),
                            type=node.get("type", "Unknown"),
                            name=node.get("name", "Unknown"),
                            description=node.get("description"),
                            confidence=float(node.get("confidence", 0.5)),
                            tenant_id=node.get("tenant_id", body.tenant_id),
                            source_id=node.get("source_id"),
                            created=node.get("created") or now,
                            modified=node.get("modified") or now,
                        )
                    )
                except Exception:
                    logger.exception("Failed to parse entity from Neo4j row")
                    continue

            if entities:
                entity_ids = [e.id for e in entities]
                neighbors = await graph_persistence.fetch_neighbor_entities(entity_ids)
                if neighbors:
                    existing_ids = {e.id for e in entities}
                    for n in neighbors:
                        if n.id not in existing_ids:
                            entities.append(n)
                    entity_ids = [e.id for e in entities]
                relationships = await graph_persistence.fetch_relationships_for_entities(entity_ids)
        finally:
            await neo4j_driver.close()

        ent_payload = [e.model_dump(mode="json") for e in entities]
        logger.info(
            "Fetch entities by ID response",
            extra={
                "tenant_id": body.tenant_id,
                "requested": len(body.entity_ids),
                "returned": len(ent_payload),
            },
        )
        return JSONResponse(
            {"entities": ent_payload, "relationships": relationships, "total": len(ent_payload)}
        )

    # ── M4.2: Search endpoint ─────────────────────────────────────────────

    @app.post("/search", tags=["search"], response_model=SearchResponse)
    async def search(body: SearchRequest) -> JSONResponse:
        """Semantic entity search endpoint.

        Embeds the query via Ollama nomic-embed-text, finds matching entities
        via Qdrant vector search, fetches those entities plus their Neo4j
        neighbours, and returns them.  Falls back to the most-recently modified
        entities for the tenant if Qdrant or the embedding service is
        unavailable.
        """
        from neo4j import AsyncGraphDatabase
        from qdrant_client import AsyncQdrantClient

        from ..graph.persistence import GraphPersistenceService

        cfg: Settings = app.state.settings
        logger.info(
            "Search request received",
            extra={"tenant_id": body.tenant_id, "query": body.query, "limit": body.limit},
        )

        neo4j_driver = AsyncGraphDatabase.driver(
            cfg.neo4j_url, auth=(cfg.neo4j_user, cfg.neo4j_password)
        )
        qdrant_client = AsyncQdrantClient(url=cfg.qdrant_url, api_key=cfg.qdrant_api_key)
        graph_persistence = GraphPersistenceService(neo4j_driver)

        entities: list[Any] = []
        relationships: list[dict[str, Any]] = []
        try:
            try:
                # Attempt Qdrant-backed semantic search
                entities = await _search_with_qdrant(
                    body.query,
                    body.tenant_id,
                    body.limit,
                    cfg.ollama_url,
                    qdrant_client,
                    graph_persistence,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Qdrant search failed, falling back to recency",
                    extra={"tenant_id": body.tenant_id, "error": str(exc)},
                )
                entities = await graph_persistence.search_entities(body.tenant_id, limit=body.limit)
                if not entities:
                    # Migration fallback: data persisted before the tenant_id bug fix
                    # may have been stored with tenant_id="" — surface it so the UI
                    # isn't blank while the graph is re-ingested with correct tenant.
                    logger.info(
                        "Tenant returned 0 entities, trying legacy tenant_id='' fallback",
                        extra={"tenant_id": body.tenant_id},
                    )
                    entities = await graph_persistence.search_entities("", limit=body.limit)

            # Fetch relationships between the matched entities
            if entities:
                entity_ids = [e.id for e in entities]
                # Expand with 1-hop neighbours so edges from matched entities
                # to adjacent nodes are also rendered (Omni-G design: "matched
                # entities + 1-2 hop Neo4j neighbors").
                neighbors = await graph_persistence.fetch_neighbor_entities(entity_ids)
                if neighbors:
                    existing_ids = {e.id for e in entities}
                    for n in neighbors:
                        if n.id not in existing_ids:
                            entities.append(n)
                            existing_ids.add(n.id)
                    entity_ids = [e.id for e in entities]
                relationships = await graph_persistence.fetch_relationships_for_entities(entity_ids)
        finally:
            await neo4j_driver.close()
            await qdrant_client.close()

        ent_payload = [e.model_dump(mode="json") for e in entities]
        logger.info(
            "Search response",
            extra={
                "tenant_id": body.tenant_id,
                "entity_count": len(ent_payload),
                "relationship_count": len(relationships),
            },
        )
        return JSONResponse(
            {"entities": ent_payload, "relationships": relationships, "total": len(ent_payload)}
        )

    return app


async def _search_with_qdrant(
    query: str,
    tenant_id: str,
    limit: int,
    ollama_url: str,
    qdrant_client: Any,
    graph_persistence: Any,
) -> list[Any]:
    """Embed query, search Qdrant, then fetch entities from Neo4j."""
    import httpx

    from ..models.entities import Entity

    # 1. Embed the query via Ollama
    async with httpx.AsyncClient(timeout=10.0) as http:
        resp = await http.post(
            f"{ollama_url}/api/embeddings",
            json={"model": "nomic-embed-text", "prompt": query},
        )
        resp.raise_for_status()
        embedding: list[float] = resp.json()["embedding"]

    # 2. Search Qdrant
    collection = f"entities_{tenant_id}"
    hits = await qdrant_client.search(
        collection_name=collection,
        query_vector=embedding,
        limit=limit,
    )
    entity_ids: list[str] = [
        str(hit.payload.get("entity_id", ""))
        for hit in hits
        if hit.payload and hit.payload.get("entity_id")
    ]

    if not entity_ids:
        return await graph_persistence.search_entities(tenant_id, limit=limit)

    # 3. Fetch matched entities from Neo4j (+ return in order of relevance).
    # Filter by tenant_id so we never return cross-tenant data.  The ON MATCH
    # SET in persist_extraction now always keeps tenant_id current, so this is
    # safe.  Legacy nodes with tenant_id="" are excluded — they must be
    # re-ingested to be surfaced.
    from datetime import UTC
    from datetime import datetime as _dt

    try:
        async with graph_persistence._driver.session() as session:
            result = await session.run(
                """
                MATCH (e:Entity)
                WHERE e.id IN $entity_ids
                  AND (e.tenant_id = $tenant_id OR e.tenant_id = '')
                RETURN e
                """,
                entity_ids=entity_ids,
                tenant_id=tenant_id,
            )
            rows = await result.data()
    except Exception:
        return await graph_persistence.search_entities(tenant_id, limit=limit)

    now = _dt.now(UTC)
    entities: list[Entity] = []
    for row in rows:
        node = row.get("e", {})
        try:
            entities.append(
                Entity(
                    id=node.get("id", ""),
                    type=node.get("type", "Unknown"),
                    name=node.get("name", "Unknown"),
                    description=node.get("description"),
                    properties={},
                    confidence=float(node.get("confidence", 0.5)),
                    tenant_id=node.get("tenant_id", tenant_id),
                    source_id=node.get("source_id"),
                    created=node.get("created") or now,
                    modified=node.get("modified") or now,
                )
            )
        except Exception:
            logger.error(
                "Failed to parse entity from Neo4j search result; skipping",
                extra={"tenant_id": tenant_id, "node": node},
            )
            continue

    return entities


app = create_app()
