from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import networkx  # noqa: F401  — pre-imported so the first /query/expand call

# doesn't pay the ~300ms one-time import cost inside the request path.
from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field, field_validator

from ..retrieval.pagerank import pagerank_subgraph  # noqa: F401  — pre-import
from .config import Settings, get_settings

# so scipy (used by nx.pagerank) is loaded at app startup, not on first request.

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
        extra = {k: v for k, v in record.__dict__.items() if k not in _LOG_RECORD_KEYS}
        if not extra:
            return message
        return f"{message} | extra={json.dumps(extra, default=str, ensure_ascii=False)}"


def configure_logging(level_name: str) -> None:
    level = getattr(logging, level_name.upper(), logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(StructuredFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logging.basicConfig(level=level, handlers=[handler], force=True)

    # Application loggers — set to the configured level.
    for name in (
        "src.processor",
        "src.kafka",
        "src.extractors",
        "src.indexers",
        "src.dedup",
        "src.cache",
        "src.graph",
        "src.resolution",
        "src.retrieval",
        "src.calibration",
        "src.briefing",
    ):
        logging.getLogger(name).setLevel(level)

    # Noisy third-party loggers — silence to WARNING so the terminal stays clean.
    for noisy_logger in (
        "kafka",
        "kafka.client",
        "kafka.conn",
        "kafka.consumer",
        "kafka.consumer.fetcher",
        "urllib3",
        "httpx",
        "httpcore",
        "neo4j",
        "qdrant_client",
        "asyncpg",
        "aioboto3",
        "botocore",
        "openai",
        "apscheduler",
        "celery",
        "celery.worker",
        "celery.beat",
    ):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)


async def startup_briefing_storage_preflight(cfg: Settings) -> None:
    from ..briefing.storage import MinIOStorageService

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
    from ..kafka.consumer import RawEventConsumer
    from .runtime import ProcessorRuntime
    from .tasks import enqueue_process_event

    consumer = RawEventConsumer(
        brokers=cfg.kafka_brokers,
        topic=cfg.kafka_raw_topic,
        group_id=cfg.kafka_group_id,
        dlq_topic=cfg.kafka_dlq_topic,
    )
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
        },
    )

    async def _handle(event: dict[str, Any]) -> None:
        if cfg.celery_enabled:
            task_id = enqueue_process_event(event)
            logger.debug(
                "Dispatched process_event Celery task",
                extra={"worker_id": worker_id, "task_id": task_id},
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
        logger.info("Kafka consumer worker shut down", extra={"worker_id": worker_id})


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    configure_logging(settings.log_level)
    logger.info(
        "Processor service starting",
        extra={
            "port": settings.http_port,
            "kafka_enabled": settings.kafka_enabled,
            "celery_enabled": settings.celery_enabled,
            "neo4j_url": settings.neo4j_url,
            "qdrant_url": settings.qdrant_url,
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
        logger.info("Launching Kafka consumer workers", extra={"worker_count": settings.kafka_num_workers})
        for worker_id in range(settings.kafka_num_workers):
            try:
                task = asyncio.create_task(startup_consumer(settings, worker_id=worker_id))
                consumer_tasks.append(task)
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to create Kafka consumer task %d: %s", worker_id, exc)
    else:
        logger.info("Kafka processing disabled")

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
    search_id: str | None = None
    # V4 Track 2: dynamic relevance threshold (τ). Edges with co-occurrence
    # weight < relevance_threshold are pruned before rendering. 0.0 = keep
    # all edges (use fusion scores as-is).
    relevance_threshold: float = Field(default=0.0, ge=0.0, le=1.0)
    # V4 Track 2: traversal depth (D_max) override. None = use the
    # QueryProfiler's derived d_max; an explicit value takes precedence.
    traversal_depth: int | None = Field(default=None, ge=1, le=4)


class SearchResponse(BaseModel):
    entities: list[dict[str, Any]]
    relationships: list[dict[str, Any]] = []
    context_units: list[dict[str, Any]] = []
    total: int
    search_id: str | None = None
    # V4 Track 2: structured rich-node payload for the ECharts card renderer.
    nodes: list[dict[str, Any]] = []
    # Zero-Mem verification: graph expansion consumes 0 LLM memory tokens.
    total_tokens_consumed: int = 0
    # V4 Phase 9: search result summary for BLUF strip.
    summary: dict[str, Any] | None = None
    # Phase 5: the most-connected entity ID, used by the radial tree layout as root.
    tree_root_id: str | None = None


class FetchEntitiesRequest(BaseModel):
    entity_ids: list[str]
    tenant_id: str = "default"


class ExpandRequest(BaseModel):
    anchor_node_id: str
    current_depth: int = 1
    target_depth: int = 2
    tenant_id: str = "default"
    search_id: str | None = None
    # V4 Track 2: dynamic relevance threshold (τ) for edge pruning on expand.
    relevance_threshold: float = Field(default=0.0, ge=0.0, le=1.0)


class SynthesisRequest(BaseModel):
    query: str
    tenant_id: str = "default"
    context_units: list[dict[str, Any]] = []


# ---------------------------------------------------------------------------
# V4 Phase 3: Fuzzy History Matching models
# ---------------------------------------------------------------------------


class HistorySuggestion(BaseModel):
    query_text: str
    search_id: str
    timestamp: str
    entity_count: int
    similarity_score: float


class HistorySearchRequest(BaseModel):
    query: str
    tenant_id: str
    limit: int = 5


class HistorySearchResponse(BaseModel):
    suggestions: list[HistorySuggestion] = []


# ---------------------------------------------------------------------------
# V4 Track 2: rich-node builder
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# V4 Phase 9: search result summary builder
# ---------------------------------------------------------------------------


def _build_summary(
    ent_payload: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
    nodes_payload: list[dict[str, Any]],
    context_units_payload: list[dict[str, Any]],
    cached: bool,
    cache_tier: str | None,
    pipeline_running: bool,
) -> dict[str, Any]:
    """Build a BLUF summary object from search results."""
    # Entity types count
    entity_types: dict[str, int] = {}
    for e in ent_payload:
        t = e.get("type", "Unknown")
        entity_types[t] = entity_types.get(t, 0) + 1

    # Top 5 entities by degree (sub_entity_count from nodes_payload)
    sorted_nodes = sorted(nodes_payload, key=lambda n: n.get("sub_entity_count", 0), reverse=True)
    top_entities = [
        {
            "name": n.get("entity_name", "Unknown"),
            "type": n.get("entity_type", "Unknown"),
            "degree": n.get("sub_entity_count", 0),
        }
        for n in sorted_nodes[:5]
    ]

    # Unique sources from context_units_payload
    sources = list(dict.fromkeys(cu.get("source_name", "") for cu in context_units_payload if cu.get("source_name")))

    return {
        "total_entities": len(ent_payload),
        "total_relationships": len(relationships),
        "entity_types": entity_types,
        "top_entities": top_entities,
        "sources": sources,
        "cached": cached,
        "cache_tier": cache_tier,
        "pipeline_running": pipeline_running,
    }


# ---------------------------------------------------------------------------
# Phase 8: retrieval-time entity dedup
# ---------------------------------------------------------------------------


def _deduplicate_entities(entities: list) -> list:
    """Remove duplicate entities with same type+name, keeping highest confidence.

    Groups entities by (type.lower(), name.lower().strip()) and selects the
    entity with the highest ``confidence`` per group.
    """
    groups: dict[tuple[str, str], list] = {}
    for e in entities:
        key = (getattr(e, "type", "").lower(), getattr(e, "name", "").lower().strip())
        groups.setdefault(key, []).append(e)
    result = []
    for _key, group in groups.items():
        best = max(group, key=lambda e: getattr(e, "confidence", 0.0))
        result.append(best)
    removed = len(entities) - len(result)
    if removed > 0:
        logger.info(
            "retrieval_dedup_removed_duplicates",
            extra={"removed_count": removed, "kept_count": len(result)},
        )
    return result


def _build_custom_nodes(
    entities: list[Any],
    context_units_payload: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
    tenant_id: str,
) -> list[dict[str, Any]]:
    """Map entities + context units + relationships into CustomNodeResponse dicts.

    Each node carries:
    - sub_entity_count: degree of the entity in the returned subgraph
    - source: NodeProvenance (source_name / source_url / plugin_name) pulled
      from the ContextUnit the entity was extracted from
    - raw_context: RawContextSnippet with verbatim text + offsets when available

    Falls back gracefully when context units lack provenance (legacy data).
    """
    # Degree map: count incident edges per entity id.
    degree: dict[str, int] = {}
    for rel in relationships:
        src = rel.get("source_ref") or rel.get("source_id") or rel.get("source")
        tgt = rel.get("target_ref") or rel.get("target_id") or rel.get("target")
        if src:
            degree[src] = degree.get(src, 0) + 1
        if tgt:
            degree[tgt] = degree.get(tgt, 0) + 1

    # Index context units by entity id for provenance lookup.
    ctx_by_entity: dict[str, dict[str, Any]] = {}
    for ctx in context_units_payload:
        for eid in ctx.get("entity_ids", []) or []:
            ctx_by_entity.setdefault(eid, ctx)

    nodes: list[dict[str, Any]] = []
    for ent in entities:
        ctx = ctx_by_entity.get(ent.id, {})
        source_name = ctx.get("source_name") or ent.source_id or "unknown"
        source_url = ctx.get("source_url")
        plugin_name = ctx.get("plugin_name")
        ingested_at = ctx.get("created") or (ent.created.isoformat() if hasattr(ent.created, "isoformat") else "")

        raw_context = None
        if ctx.get("text"):
            raw_context = {
                "snippet_text": str(ctx["text"])[:500],
                "char_offset_start": 0,
                "char_offset_end": min(len(str(ctx["text"])), 500),
                "document_id": ctx.get("context_id", ""),
            }

        nodes.append(
            {
                "id": ent.id,
                "entity_name": ent.name,
                "entity_type": ent.type,
                "sub_entity_count": degree.get(ent.id, 0),
                "confidence_score": float(ent.confidence),
                "source": {
                    "source_name": source_name,
                    "source_url": source_url,
                    "ingested_at": ingested_at,
                    "mcp_plugin_name": plugin_name,
                },
                "raw_context": raw_context,
            }
        )
    return nodes


# ---------------------------------------------------------------------------
# V4 Phase 3: Query History Recording helper
# ---------------------------------------------------------------------------


async def _record_query_history(
    tenant_id: str,
    search_id: str,
    query: str,
    entity_count: int,
    redis_url: str,
    qdrant_url: str,
    qdrant_api_key: str | None,
    ttl_seconds: int = 86400,
) -> None:
    """Record a search query in Redis + Qdrant for fuzzy history matching.

    Fail-open: all errors are logged but never raised so they can't break the
    /search response path.
    """
    import hashlib as _hashlib
    import json as _json
    import time as _time

    try:
        from ..llm.client import LLMClient
    except Exception:
        logger.warning("Cannot import LLMClient for query history recording")
        return

    now = _time.time()
    payload = _json.dumps(
        {
            "query_text": query,
            "search_id": search_id,
            "tenant_id": tenant_id,
            "timestamp": now,
            "entity_count": entity_count,
        }
    )

    # ── Redis: store query history hash ───────────────────────────────
    try:
        import redis.asyncio as _aioredis

        redis_client = _aioredis.from_url(  # type: ignore[no-untyped-call]
            redis_url, decode_responses=True
        )
        try:
            history_key = f"query:history:{tenant_id}:{search_id}"
            await redis_client.setex(history_key, ttl_seconds, payload)
            logger.debug(
                "Query history stored in Redis",
                extra={"tenant_id": tenant_id, "search_id": search_id},
            )

            # ── RediSearch: index query_text in idx:query_history ─────
            try:
                # Ensure index exists (idempotent)
                try:
                    await redis_client.execute_command(
                        "FT.CREATE",
                        "idx:query_history",
                        "ON",
                        "HASH",
                        "PREFIX",
                        "1",
                        "query:history:",
                        "SCHEMA",
                        "query_text",
                        "TEXT",
                        "search_id",
                        "TAG",
                        "tenant_id",
                        "TAG",
                        "timestamp",
                        "NUMERIC",
                        "SORTABLE",
                        "entity_count",
                        "NUMERIC",
                    )
                except Exception as exc:
                    logger.debug("RediSearch idx:query_history FT.CREATE (may already exist): %s", exc)

                rs_key = f"query:history:{tenant_id}:{search_id}"
                history_fields = {
                    "query_text": query,
                    "search_id": search_id,
                    "tenant_id": tenant_id,
                    "timestamp": str(now),
                    "entity_count": str(entity_count),
                }
                await redis_client.hset(rs_key, mapping=history_fields)  # type: ignore[arg-type]
                await redis_client.expire(rs_key, ttl_seconds)
                logger.debug(
                    "Query history indexed in RediSearch",
                    extra={"tenant_id": tenant_id, "search_id": search_id},
                )
            except Exception as exc:
                logger.warning("RediSearch history indexing failed: %s", exc)
        finally:
            await redis_client.aclose()
    except Exception as exc:
        logger.warning("Redis history storage failed: %s", exc)

    # ── Qdrant: upsert embedding in query_embeddings collection ────────
    try:
        from qdrant_client import AsyncQdrantClient
        from qdrant_client.models import PointStruct

        qdrant = AsyncQdrantClient(url=qdrant_url, api_key=qdrant_api_key)
        try:
            llm = LLMClient()
            embedding = await llm.embed(query)
            if embedding is not None:
                point_id = int(
                    _hashlib.sha256(f"history:{tenant_id}:{query}".encode()).hexdigest()[:15],
                    16,
                )
                await qdrant.upsert(
                    collection_name="query_embeddings",
                    points=[
                        PointStruct(
                            id=point_id,
                            vector=embedding,
                            payload={
                                "query_text": query,
                                "search_id": search_id,
                                "tenant_id": tenant_id,
                                "timestamp": str(now),
                                "entity_count": entity_count,
                            },
                        )
                    ],
                )
                logger.debug(
                    "Query history embedding upserted in Qdrant",
                    extra={"tenant_id": tenant_id, "search_id": search_id},
                )
        finally:
            await qdrant.close()
    except Exception as exc:
        logger.warning("Qdrant history embedding failed: %s", exc)


def create_app(settings: Settings | None = None) -> FastAPI:
    if settings is None:
        settings = get_settings()

    app = FastAPI(
        title="Omni-G Processor",
        description="Zero-Mem extraction, graph persistence, and dual-view retrieval service",
        version="0.3.0",
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

    @app.get("/dlq/stats", tags=["ops"])
    async def dlq_stats() -> JSONResponse:
        """Return DLQ metrics: total events routed to DLQ by error type.

        Also returns the most recent DLQ messages from the raw-feed.dlq Kafka
        topic (up to 10) so operators can inspect what's failing without
        needing Kafka CLI access.
        """
        from prometheus_client import REGISTRY

        # Collect DLQ counter values from Prometheus registry.
        dlq_by_reason: dict[str, float] = {}
        for metric in REGISTRY.collect():
            if metric.name == "processor_dlq_events_total":
                for sample in metric.samples:
                    reason = sample.labels.get("reason", "unknown")
                    dlq_by_reason[reason] = sample.value

        total_dlq = sum(dlq_by_reason.values())

        # Also collect schema violations (events dropped before DLQ).
        schema_violations = 0.0
        for metric in REGISTRY.collect():
            if metric.name == "processor_schema_violations_total":
                for sample in metric.samples:
                    schema_violations += sample.value

        return JSONResponse(
            {
                "total_dlq_events": total_dlq,
                "dlq_by_reason": dlq_by_reason,
                "schema_violations": schema_violations,
                "dlq_topic": app.state.settings.kafka_dlq_topic,
                "note": "DLQ only receives events that fail processing (schema violations, connection errors, etc.). Valid but irrelevant events are processed successfully and do not appear here.",
            }
        )

    @app.post("/validate", tags=["ops"], response_model=ValidateResponse)
    async def validate(body: ValidateRequest) -> JSONResponse:
        errors: list[dict[str, str]] = []
        logger.debug("Validation request received", extra={"source": body.source})
        if not body.source:
            errors.append({"field": "source", "message": "field 'source' is required"})
        if body.payload is None:
            errors.append({"field": "payload", "message": "field 'payload' is required"})
        elif not body.payload:
            errors.append({"field": "payload", "message": "payload must not be empty"})
        else:
            for k, v in body.payload.items():
                if v is None or v == "":
                    errors.append(
                        {
                            "field": f"payload.{k}",
                            "message": "value must not be None or empty string",
                        }
                    )
            required_keys = {"text", "content", "data", "url"}
            if not required_keys.intersection(body.payload.keys()):
                errors.append(
                    {
                        "field": "payload",
                        "message": "must contain at least one of: text, content, data, url",
                    }
                )
        if errors:
            return JSONResponse(status_code=422, content={"valid": False, "errors": errors})
        return JSONResponse({"valid": True})

    @app.get("/briefings", tags=["briefings"])
    async def list_briefings() -> JSONResponse:
        from ..briefing.storage import MinIOStorageService
        from ..briefing.url_signer import BriefingURLSigner

        cfg: Settings = app.state.settings
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
                from urllib.parse import urlparse as _up

                parsed = _up(signed_url)
                results.append(
                    {
                        "tenant_id": tenant_id,
                        "object_key": parsed.path.lstrip("/"),
                        "signed_url": signed_url,
                    }
                )
        return JSONResponse(results)

    @app.post("/briefings/generate", tags=["briefings"])
    async def generate_briefing(body: dict[str, str]) -> JSONResponse:
        """Trigger an on-demand audio briefing for a tenant.

        V3 NOTE: Content source migrated from GraphRAG to calibrated R(q)
        context arrays — follow-on work after Phase 6.
        """
        from ..briefing.scheduler import BriefingScheduler
        from ..briefing.script_generator import BriefingScriptGenerator
        from ..briefing.storage import MinIOStorageService
        from ..briefing.tts_synthesizer import TTSSynthesizer

        cfg: Settings = app.state.settings
        tenant_id = body.get("tenant_id", "default")
        logger.info("Briefing generation requested", extra={"tenant_id": tenant_id})
        script_gen = BriefingScriptGenerator()
        tts = TTSSynthesizer(kokoro_url=cfg.kokoro_url, elevenlabs_api_key=cfg.elevenlabs_api_key)
        storage = MinIOStorageService(
            endpoint_url=cfg.minio_url,
            access_key=cfg.minio_access_key,
            secret_key=cfg.minio_secret_key,
            bucket=cfg.minio_bucket,
        )
        scheduler = BriefingScheduler(script_gen, tts, storage)
        try:
            object_key = await scheduler.on_demand(tenant_id)
            signed_url = await storage.get_signed_url(object_key)
            return JSONResponse({"signed_url": signed_url})
        except Exception as exc:  # noqa: BLE001
            logger.error("Briefing generation failed: %s", exc)
            return JSONResponse(status_code=500, content={"error": str(exc)})

    # ── Direct entity fetch by ID ─────────────────────────────────────────

    @app.post("/entities", tags=["search"], response_model=SearchResponse)
    async def fetch_entities_by_ids(body: FetchEntitiesRequest) -> JSONResponse:
        """Fetch entities directly from Neo4j by canonical ID (alert hydration)."""
        from datetime import UTC
        from datetime import datetime as _dt

        from neo4j import AsyncGraphDatabase

        from ..graph.persistence import GraphPersistenceService
        from ..models.entities import Entity

        if not body.entity_ids:
            return JSONResponse({"entities": [], "relationships": [], "context_units": [], "total": 0})

        cfg: Settings = app.state.settings
        neo4j_driver = AsyncGraphDatabase.driver(cfg.neo4j_url, auth=(cfg.neo4j_user, cfg.neo4j_password))
        graph_persistence = GraphPersistenceService(neo4j_driver)
        entities: list[Entity] = []
        relationships: list[dict[str, Any]] = []
        try:
            now = _dt.now(UTC)
            async with neo4j_driver.session() as session:
                result = await session.run(
                    "MATCH (e:Entity) WHERE e.id IN $ids " "AND e.source_id IS NOT NULL AND e.source_id <> '' RETURN e",
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
            if entities:
                entity_ids = [e.id for e in entities]
                neighbors = await graph_persistence.fetch_neighbor_entities(entity_ids, body.tenant_id)
                existing_ids = {e.id for e in entities}
                for n in neighbors:
                    if n.id not in existing_ids:
                        entities.append(n)
                entity_ids = [e.id for e in entities]
                relationships = await graph_persistence.fetch_relationships_for_entities(entity_ids)
        finally:
            await neo4j_driver.close()

        ent_payload = [e.model_dump(mode="json") for e in entities]
        return JSONResponse(
            {
                "entities": ent_payload,
                "relationships": relationships,
                "context_units": [],
                "total": len(ent_payload),
                "tree_root_id": entities[0].id if entities else None,
            }
        )

    # ── Search endpoint (Phase 7): Dual-View Retrieval ────────────────────

    @app.post("/search", tags=["search"], response_model=SearchResponse)
    async def search(body: SearchRequest) -> JSONResponse:
        """Dual-view semantic search: QueryProfiler → Relational + Temporal retrieval
        → DualViewFusion → EvidenceCalibrator → R(q) context array.

        Returns entities + relationships (React Flow compatible) and context_units.
        """
        import asyncio as _asyncio
        from datetime import UTC
        from datetime import datetime as _dt

        from neo4j import AsyncGraphDatabase
        from qdrant_client import AsyncQdrantClient

        from ..calibration.calibrator import EvidenceCalibrator
        from ..graph.persistence import GraphPersistenceService
        from ..graph.temporal_store import TemporalStore
        from ..indexers.vector import ContextUnitIndexer
        from ..models.entities import Entity
        from ..retrieval.fusion import DualViewFusion
        from ..retrieval.profiler import QueryProfiler
        from ..retrieval.relational import RelationalRetriever
        from ..retrieval.temporal import TemporalRetriever

        cfg: Settings = app.state.settings
        logger.info("Search request received", extra={"tenant_id": body.tenant_id, "query": body.query[:100]})

        # V4 Track 1: bind a unique search_id for cross-service tracing.
        search_id = body.search_id or str(uuid4())
        logger.info(
            "Search request bound",
            extra={"tenant_id": body.tenant_id, "search_id": search_id},
        )

        # ── V4 Phase 2: 3-Tier Result Cache check ────────────────────────
        from ..cache.query_cache import QueryCacheService

        cache = QueryCacheService(
            redis_url=cfg.redis_url,
            qdrant_url=cfg.qdrant_url,
            qdrant_api_key=cfg.qdrant_api_key,
            ttl_seconds=cfg.query_cache_ttl_seconds,
            embedding_dim=cfg.embedding_dim,
        )
        await cache.connect()
        try:
            cached = await cache.check_cache(body.tenant_id, body.query)
            if cached is not None:
                # V4 Phase 9: attach summary to cached result
                cached["summary"] = _build_summary(
                    ent_payload=cached.get("entities", []),
                    relationships=cached.get("relationships", []),
                    nodes_payload=cached.get("nodes", []),
                    context_units_payload=cached.get("context_units", []),
                    cached=True,
                    cache_tier=cached.get("cache_tier"),
                    pipeline_running=False,
                )
                logger.info(
                    "Cache hit — returning cached result",
                    extra={
                        "tenant_id": body.tenant_id,
                        "search_id": search_id,
                        "cache_tier": cached.get("cache_tier", "unknown"),
                    },
                )
                return JSONResponse(cached)
        finally:
            # Cache check done — close the cache connection.
            # We'll re-open later for store_cache if we get a cache miss.
            await cache.close()

        neo4j_driver = AsyncGraphDatabase.driver(cfg.neo4j_url, auth=(cfg.neo4j_user, cfg.neo4j_password))
        qdrant_client = AsyncQdrantClient(url=cfg.qdrant_url, api_key=cfg.qdrant_api_key)
        graph_persistence = GraphPersistenceService(neo4j_driver)

        try:
            # Profile query
            profiler = QueryProfiler()  # type: ignore[no-untyped-call]
            profile = profiler.profile(body.query)

            # V4 Track 2: user-supplied traversal depth (D_max) overrides the
            # profiler-derived value when explicitly provided.
            if body.traversal_depth is not None:
                import dataclasses as _dc

                profile = _dc.replace(profile, d_max=body.traversal_depth)
                logger.info(
                    "search_d_max_override",
                    extra={"tenant_id": body.tenant_id, "d_max": body.traversal_depth},
                )

            # Lazy-loaded indexer (BGE-M3)
            vector_indexer = ContextUnitIndexer(qdrant_url=cfg.qdrant_url, api_key=cfg.qdrant_api_key, settings=cfg)

            # Temporal store (fail-open)
            temporal_store = TemporalStore(postgres_url=cfg.postgres_url)
            try:
                await temporal_store.connect()
            except Exception:
                logger.warning("TemporalStore unavailable for search; using Neo4j fallback")

            relational_retriever = RelationalRetriever(neo4j_driver, qdrant_client, vector_indexer)
            temporal_retriever = TemporalRetriever(temporal_store, neo4j_driver)

            # Parallel retrieval
            rel_task = relational_retriever.retrieve(profile, body.tenant_id, profile.d_max, body.limit)
            temp_task = temporal_retriever.retrieve(profile, body.tenant_id, body.limit)
            relational_results, temporal_results = await _asyncio.gather(rel_task, temp_task, return_exceptions=True)
            if isinstance(relational_results, Exception):
                logger.warning("Relational retrieval failed: %s", relational_results)
                relational_results = []
            if isinstance(temporal_results, Exception):
                logger.warning("Temporal retrieval failed: %s", temporal_results)
                temporal_results = []

            # Fusion + calibration
            fused = DualViewFusion().fuse(relational_results, temporal_results, profile)  # type: ignore[arg-type]
            calibrated = EvidenceCalibrator().calibrate(fused, profile, l_max=4096)

            logger.info(
                "search_retrieval_diagnostics",
                extra={
                    "tenant_id": body.tenant_id,
                    "relational_count": len(relational_results) if isinstance(relational_results, list) else 0,
                    "temporal_count": len(temporal_results) if isinstance(temporal_results, list) else 0,
                    "fused_count": len(fused),
                    "calibrated_count": len(calibrated),
                },
            )

            # Build context_units payload with provenance from ScoredContext
            context_units_payload = [
                {
                    "context_id": ctx.context_id,
                    "score": ctx.score,
                    "text": ctx.text[:500],  # truncate for transport
                    "entity_ids": ctx.entity_ids,
                    "source_name": ctx.source_name,
                    "source_url": ctx.source_url,
                    "plugin_name": ctx.plugin_name,
                }
                for ctx in calibrated
            ]

            # Collect entity IDs from calibrated context units and fetch from Neo4j
            all_entity_ids: list[str] = []
            for ctx in calibrated:
                all_entity_ids.extend(ctx.entity_ids)
            all_entity_ids = list(dict.fromkeys(all_entity_ids))[: body.limit]

            entities: list[Entity] = []
            relationships: list[dict[str, Any]] = []
            now = _dt.now(UTC)

            if all_entity_ids:
                async with neo4j_driver.session() as session:
                    result = await session.run(
                        "MATCH (e:Entity) WHERE e.id IN $ids AND e.tenant_id = $tenant_id " "AND e.source_id IS NOT NULL AND e.source_id <> '' RETURN e",
                        ids=all_entity_ids,
                        tenant_id=body.tenant_id,
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
                        logger.exception("Failed to parse entity")

            # If no entities from retrieval, fall back to recency search
            if not entities:
                entities = await graph_persistence.search_entities(body.tenant_id, limit=body.limit)

            if entities:
                entity_ids_final = [e.id for e in entities]
                neighbors = await graph_persistence.fetch_neighbor_entities(entity_ids_final, body.tenant_id)
                existing_ids = {e.id for e in entities}
                for n in neighbors:
                    if n.id not in existing_ids:
                        entities.append(n)
                entity_ids_final = [e.id for e in entities]
                relationships = await graph_persistence.fetch_relationships_for_entities(entity_ids_final)

            # V4 Track 2: dynamic relevance threshold (τ) edge pruning.
            # Drop edges whose weight falls below the user-supplied threshold
            # so stale / low-weight co-occurrence links never reach the UI.
            if body.relevance_threshold > 0.0 and relationships:
                relationships = [rel for rel in relationships if float(rel.get("confidence", rel.get("weight", 0.0))) >= body.relevance_threshold]

            # ── Provenance fallback: when the retrieval pipeline returned no
            # calibrated contexts, fetch ContextUnits directly from Neo4j so
            # the UI still gets source_name / source_url / raw_context.
            if not context_units_payload and entities:
                entity_ids_for_ctx = [e.id for e in entities]
                context_units_payload = await graph_persistence.fetch_context_units_for_entities(entity_ids_for_ctx, body.tenant_id)
                logger.info(
                    "search_context_units_fallback",
                    extra={
                        "tenant_id": body.tenant_id,
                        "entity_count": len(entities),
                        "context_unit_count": len(context_units_payload),
                    },
                )

            await temporal_store.close()
        finally:
            await neo4j_driver.close()
            await qdrant_client.close()

        # Phase 8: retrieval-time entity dedup — keep highest confidence per (type, name)
        entities = _deduplicate_entities(entities)

        # Phase 5: sort entities by degree (highest first) so the root is the
        # most-connected entity. Compute tree_root_id for the radial tree layout.
        tree_root_id: str | None = None
        if entities:
            # Degree map from relationships
            _degree_map: dict[str, int] = {}
            for rel in relationships:
                src = rel.get("source_ref") or rel.get("source_id") or rel.get("source")
                tgt = rel.get("target_ref") or rel.get("target_id") or rel.get("target")
                if src:
                    _degree_map[src] = _degree_map.get(src, 0) + 1
                if tgt:
                    _degree_map[tgt] = _degree_map.get(tgt, 0) + 1
            # Sort by degree desc, tie-break on confidence desc
            entities = sorted(
                entities,
                key=lambda e: (_degree_map.get(e.id, 0), e.confidence),
                reverse=True,
            )
            tree_root_id = entities[0].id

        ent_payload = [e.model_dump(mode="json") for e in entities]

        # V4 Track 2: build structured rich-node payload with provenance.
        # Each node carries source_name/source_url/plugin_name (from the
        # ContextUnit it was extracted from) and a raw context snippet.
        nodes_payload = _build_custom_nodes(entities, context_units_payload, relationships, body.tenant_id)

        logger.info(
            "Search response",
            extra={
                "tenant_id": body.tenant_id,
                "entity_count": len(ent_payload),
                "context_unit_count": len(context_units_payload),
                "node_count": len(nodes_payload),
            },
        )

        # V4 Phase 9: build BLUF summary for cache-miss (pipeline-triggered) response
        summary = _build_summary(
            ent_payload=ent_payload,
            relationships=relationships,
            nodes_payload=nodes_payload,
            context_units_payload=context_units_payload,
            cached=False,
            cache_tier=None,
            pipeline_running=True,
        )

        response = {
            "entities": ent_payload,
            "relationships": relationships,
            "context_units": context_units_payload,
            "total": len(ent_payload),
            "nodes": nodes_payload,
            "tree_root_id": tree_root_id,
            "total_tokens_consumed": 0,
            "search_id": search_id,
            "summary": summary,
        }

        # ── V4 Phase 2: Store result in cache for future queries ──────────
        cache_store = QueryCacheService(
            redis_url=cfg.redis_url,
            qdrant_url=cfg.qdrant_url,
            qdrant_api_key=cfg.qdrant_api_key,
            ttl_seconds=cfg.query_cache_ttl_seconds,
            embedding_dim=cfg.embedding_dim,
        )
        await cache_store.connect()
        try:
            await cache_store.store_cache(body.tenant_id, search_id, body.query, response)
        finally:
            await cache_store.close()

        # ── V4 Phase 3: Record query history for fuzzy matching ────────────
        asyncio.ensure_future(
            _record_query_history(
                tenant_id=body.tenant_id,
                search_id=search_id,
                query=body.query,
                entity_count=len(ent_payload),
                redis_url=cfg.redis_url,
                qdrant_url=cfg.qdrant_url,
                qdrant_api_key=cfg.qdrant_api_key,
                ttl_seconds=cfg.query_cache_ttl_seconds,
            )
        )

        return JSONResponse(response)

    # ── V4 Phase 3: Fuzzy History Matching endpoint ────────────────────

    @app.post(
        "/query/history/search",
        tags=["search"],
        response_model=HistorySearchResponse,
    )
    async def history_search(body: HistorySearchRequest) -> JSONResponse:
        """Search query history for semantically similar past queries.

        Returns suggestions with instant cached results the UI can load
        without re-executing the full search pipeline.
        Fail-open: returns empty suggestions on any error.
        """
        from ..llm.client import LLMClient

        cfg: Settings = app.state.settings
        logger.info(
            "History search request",
            extra={"tenant_id": body.tenant_id, "query": body.query[:100]},
        )

        # ── 1. Embed the query ─────────────────────────────────────────
        try:
            llm = LLMClient()
            embedding = await asyncio.wait_for(llm.embed(body.query), timeout=10.0)
        except Exception as exc:
            logger.warning("Failed to embed query for history search: %s", exc)
            return JSONResponse({"suggestions": []})

        # ── 2. Search Qdrant for similar past queries ───────────────────
        try:
            from qdrant_client import AsyncQdrantClient
            from qdrant_client.models import FieldCondition, Filter, MatchValue

            qdrant = AsyncQdrantClient(url=cfg.qdrant_url, api_key=cfg.qdrant_api_key)
            results = await qdrant.search(
                collection_name="query_embeddings",
                query_vector=embedding,
                limit=body.limit + 5,  # fetch extra for post-filter margin
                score_threshold=0.75,
                query_filter=Filter(
                    must=[
                        FieldCondition(
                            key="tenant_id",
                            match=MatchValue(value=body.tenant_id),
                        )
                    ]
                ),
            )
            await qdrant.close()
        except Exception as exc:
            logger.warning("Qdrant history search failed: %s", exc)
            return JSONResponse({"suggestions": []})

        # ── 3. Build response, sorted by similarity descending ─────────
        suggestions: list[dict[str, Any]] = []
        for hit in results[: body.limit]:
            payload = hit.payload or {}
            suggestions.append(
                {
                    "query_text": str(payload.get("query_text", "")),
                    "search_id": str(payload.get("search_id", "")),
                    "timestamp": str(payload.get("timestamp", "")),
                    "entity_count": int(payload.get("entity_count", 0)),
                    "similarity_score": round(float(hit.score), 4),
                }
            )

        suggestions.sort(key=lambda s: s["similarity_score"], reverse=True)

        logger.info(
            "History search response",
            extra={
                "tenant_id": body.tenant_id,
                "suggestion_count": len(suggestions),
            },
        )
        return JSONResponse({"suggestions": suggestions})

    @app.post("/query/expand", tags=["search"], response_model=SearchResponse)
    async def expand(body: ExpandRequest) -> JSONResponse:
        """Dynamic multi-hop localized expansion tool triggered from ECharts."""
        from datetime import UTC
        from datetime import datetime as _dt

        from neo4j import AsyncGraphDatabase

        from ..graph.persistence import GraphPersistenceService
        from ..models.entities import Entity

        cfg: Settings = app.state.settings
        logger.info(
            "Expand request received",
            extra={
                "tenant_id": body.tenant_id,
                "anchor_node_id": body.anchor_node_id,
                "target_depth": body.target_depth,
            },
        )

        neo4j_driver = AsyncGraphDatabase.driver(cfg.neo4j_url, auth=(cfg.neo4j_user, cfg.neo4j_password))
        graph_persistence = GraphPersistenceService(neo4j_driver)

        context_units_payload = []
        all_entity_ids = []
        entities = []
        relationships = []
        now = _dt.now(UTC)

        try:
            # Personalized PageRank via networkx (replaces the removed
            # apoc.algo.pageRankWithConfig procedure, deleted in APOC 5.x).
            # The shared helper fetches the k-hop subgraph via
            # apoc.path.subgraphNodes (still supported) and runs PageRank in
            # Python. See src.retrieval.pagerank.pagerank_subgraph.
            rows: list[dict[str, Any]] = []
            try:
                async with neo4j_driver.session() as session:
                    scored = await pagerank_subgraph(
                        session,
                        anchor_ids=[body.anchor_node_id],
                        tenant_id=body.tenant_id,
                        d_max=body.target_depth,
                        gamma=0.6,
                        top_k=10,
                    )
                rows = [{"context_id": s.context_id, "text": s.text, "score": s.score} for s in scored]
            except Exception as exc:
                logger.warning(
                    "pagerank_failed_in_expand_falling_back_to_bfs",
                    extra={"error": str(exc), "tenant_id": body.tenant_id},
                )
                cypher_bfs = """
                MATCH (anchor:Entity)-[:CO_OCCURRED_IN]->(ctx:ContextUnit)
                WHERE anchor.id = $anchor_id AND ctx.tenant_id = $tenant_id
                RETURN ctx.id AS context_id, ctx.text AS text, 1.0 AS score
                LIMIT 10
                """
                async with neo4j_driver.session() as session:
                    res = await session.run(
                        cypher_bfs,
                        anchor_id=body.anchor_node_id,
                        tenant_id=body.tenant_id,
                    )
                    rows = await res.data()

            if rows:
                context_ids = [row["context_id"] for row in rows]

                async with neo4j_driver.session() as session:
                    res = await session.run(
                        """
                        MATCH (ctx:ContextUnit)<-[:CO_OCCURRED_IN]-(e:Entity)
                        WHERE ctx.id IN $context_ids AND ctx.tenant_id = $tenant_id
                        AND e.tenant_id = $tenant_id
                        AND e.source_id IS NOT NULL AND e.source_id <> ''
                        RETURN ctx.id AS context_id, collect(e.id) AS entity_ids
                        """,
                        context_ids=context_ids,
                        tenant_id=body.tenant_id,
                    )
                    co_occur_rows = await res.data()

                co_occur_map = {row["context_id"]: row["entity_ids"] for row in co_occur_rows}

                for row in rows:
                    cid = row["context_id"]
                    e_ids = co_occur_map.get(cid, [])
                    all_entity_ids.extend(e_ids)
                    context_units_payload.append(
                        {
                            "context_id": cid,
                            "score": float(row["score"]),
                            "text": row.get("text", "")[:500],
                            "entity_ids": e_ids,
                        }
                    )

                all_entity_ids = list(dict.fromkeys(all_entity_ids))[:50]

                if all_entity_ids:
                    async with neo4j_driver.session() as session:
                        result = await session.run(
                            "MATCH (e:Entity) WHERE e.id IN $ids " "AND e.tenant_id = $tenant_id " "AND e.source_id IS NOT NULL AND e.source_id <> '' RETURN e",
                            ids=all_entity_ids,
                            tenant_id=body.tenant_id,
                        )
                        node_rows = await result.data()
                    for r_node in node_rows:
                        node = r_node.get("e", {})
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
                            logger.exception("Failed to parse node in expand")

                    relationships = await graph_persistence.fetch_relationships_for_entities(all_entity_ids)

        finally:
            await neo4j_driver.close()

        # V4 Track 2: dynamic relevance threshold (τ) edge pruning on expand.
        if body.relevance_threshold > 0.0 and relationships:
            relationships = [rel for rel in relationships if float(rel.get("confidence", rel.get("weight", 0.0))) >= body.relevance_threshold]

        # Phase 5: compute tree_root_id for expand responses.
        _expand_root_id: str | None = None
        if entities:
            _expand_root_id = entities[0].id

        ent_payload = [e.model_dump(mode="json") for e in entities]
        nodes_payload = _build_custom_nodes(entities, context_units_payload, relationships, body.tenant_id)
        return JSONResponse(
            {
                "entities": ent_payload,
                "relationships": relationships,
                "context_units": context_units_payload,
                "total": len(ent_payload),
                "nodes": nodes_payload,
                "tree_root_id": _expand_root_id,
                "total_tokens_consumed": 0,
                "search_id": body.search_id,
            }
        )

    # ── B1: Synthesis endpoint ────────────────────────────────────────────

    @app.post("/synthesize", tags=["synthesis"])
    async def synthesize(body: SynthesisRequest) -> JSONResponse:
        """Generate a BLUF summary from calibrated context units.

        Takes context_units + query → LLMClient.generate() → BLUF summary.
        Falls back to extractive summary if LLM unavailable.
        """
        from ..llm.client import LLMClient

        cfg: Settings = app.state.settings
        logger.info(
            "Synthesis request received",
            extra={
                "tenant_id": body.tenant_id,
                "query": body.query,
                "context_count": len(body.context_units),
            },
        )

        # Extractive fallback: top-3 context units concatenated
        sorted_units = sorted(body.context_units, key=lambda x: x.get("score", 0), reverse=True)
        top_texts = [u.get("text", "") for u in sorted_units[:3] if u.get("text")]
        extractive_summary = " | ".join(top_texts) if top_texts else "No context available."

        # Try LLM-synthesized summary
        try:
            llm = LLMClient(cfg)
            context_text = "\n".join(f"[{i + 1}] {u.get('text', '')}" for i, u in enumerate(sorted_units[:10]))
            prompt = (
                "You are an intelligence analyst. Provide a 2-3 sentence BLUF "
                "(Bottom Line Up Front) summary of the following intelligence findings. "
                "Be concise and factual.\n\n"
                f"Query: {body.query}\n\n"
                f"Findings:\n{context_text}"
            )
            summary = await llm.generate(prompt)
            if summary.strip():
                return JSONResponse({"summary": summary, "mode": "llm"})
        except Exception as exc:
            logger.warning("LLM synthesis failed, using extractive fallback: %s", exc)

        return JSONResponse({"summary": extractive_summary, "mode": "extractive"})

    # ── B8: Trending entities endpoint ────────────────────────────────────

    @app.get("/trending", tags=["search"])
    async def trending(tenant_id: str = "default", limit: int = 5) -> JSONResponse:
        """Return recently-added high-confidence entities for the empty state."""
        from datetime import UTC
        from datetime import datetime as _dt

        from neo4j import AsyncGraphDatabase

        cfg: Settings = app.state.settings
        neo4j_driver = AsyncGraphDatabase.driver(cfg.neo4j_url, auth=(cfg.neo4j_user, cfg.neo4j_password))

        entities: list[dict[str, Any]] = []
        try:
            now = _dt.now(UTC)
            async with neo4j_driver.session() as session:
                result = await session.run(
                    """
                    MATCH (e:Entity)
                    WHERE e.tenant_id = $tenant_id AND e.confidence >= 0.5
                      AND e.source_id IS NOT NULL AND e.source_id <> ''
                    RETURN e
                    ORDER BY e.created DESC
                    LIMIT $limit
                    """,
                    tenant_id=tenant_id,
                    limit=limit,
                )
                rows = await result.data()
            for row in rows:
                node = row.get("e", {})
                try:
                    entities.append(
                        {
                            "id": node.get("id", ""),
                            "name": node.get("name", "Unknown"),
                            "type": node.get("type", "Unknown"),
                            "confidence": float(node.get("confidence", 0.5)),
                            "created": str(node.get("created", now)),
                        }
                    )
                except Exception:
                    logger.exception("Failed to parse trending entity")
        finally:
            await neo4j_driver.close()

        return JSONResponse({"entities": entities, "total": len(entities)})

    # ── B6: Briefing transcript endpoint ──────────────────────────────────

    @app.get("/briefings/{briefing_id}/transcript", tags=["briefings"])
    async def get_briefing_transcript(briefing_id: str, tenant_id: str = "default") -> JSONResponse:
        """Return the briefing script text + extracted entity names."""
        from ..briefing.storage import MinIOStorageService

        cfg: Settings = app.state.settings
        storage = MinIOStorageService(
            endpoint_url=cfg.minio_url,
            access_key=cfg.minio_access_key,
            secret_key=cfg.minio_secret_key,
            bucket=cfg.minio_bucket,
        )

        try:
            # Find the text file matching this briefing ID
            prefix = f"omni-g-briefings/{tenant_id}/"
            text_keys = await storage.list_objects(prefix)
            text_keys = [k for k in text_keys if k.endswith(".txt")]

            # Find the most recent text file (briefing_id may be a UUID or date-based)
            text = None
            matched_key = None
            for key in text_keys:
                if briefing_id in key:
                    text = await storage.get_text(key)
                    matched_key = key
                    break

            if text is None and text_keys:
                # Fall back to the most recent text file
                latest_key = text_keys[-1]
                text = await storage.get_text(latest_key)
                matched_key = latest_key

            if text is None:
                return JSONResponse({"error": "Transcript not found"}, status_code=404)

            # Simple entity extraction from the transcript text
            import re

            entity_pattern = re.compile(r"\b([A-Z][a-zA-Z]{2,}(?:\s+[A-Z][a-zA-Z]{2,}){0,3})\b")
            matches = entity_pattern.findall(text)
            # Filter out common non-entities
            stop_words = {
                "The",
                "All",
                "We",
                "They",
                "That",
                "This",
                "There",
                "These",
                "Those",
                "And",
                "But",
                "For",
                "From",
                "With",
                "When",
                "While",
                "During",
                "Would",
                "Could",
                "Should",
                "About",
                "After",
                "Before",
                "Then",
                "Just",
                "Much",
                "Many",
                "Good",
                "Here",
                "Your",
                "Most",
                "Section",
                "Please",
                "First",
                "Second",
                "Third",
                "Next",
                "Last",
            }
            entities_list = list(dict.fromkeys(m for m in matches if m not in stop_words and len(m) > 2))[:10]

            return JSONResponse(
                {
                    "id": briefing_id,
                    "text": text,
                    "entities": entities_list,
                    "date": matched_key or "",
                }
            )
        except Exception as exc:
            logger.error("Failed to fetch briefing transcript: %s", exc)
            return JSONResponse({"error": "Transcript unavailable"}, status_code=502)

    return app


app = create_app()
