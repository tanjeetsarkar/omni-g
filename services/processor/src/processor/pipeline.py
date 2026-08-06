"""V3 Zero-Mem processing pipeline.

Stages
------
1. Schema validation  — validates the RawEventEnvelope; raises SchemaViolationError → DLQ.
2. Deduplication      — Redis SHA-256 check; silently drops duplicates.
3. ZeroMem extraction — NER-based entity extraction (spaCy + GLiNER, zero LLM calls):
     a. Create ContextUnit
     b. ZeroMemExtractor.extract() → entities + co-occurrence weights
     c. Persist ContextUnit node + CO_OCCURRED_IN edges in Neo4j
     d. Link to previous ContextUnit (NEXT_CONTEXT) for same source
     e. Index ContextUnit vector in Qdrant via ContextUnitIndexer (BGE-M3)
     f. Insert temporal record in Postgres via TemporalStore
4. Entity resolution  — Qdrant vector blocking + Neo4j structural matching.
5. Graph persistence  — atomic Neo4j write of Entity + Relationship nodes.
6. Alert publishing   — Kafka analyst-alerts if extraction_confidence > 0.5.
"""

from __future__ import annotations

import hashlib
import logging
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from prometheus_client import Counter, Histogram
from pydantic import BaseModel, Field, model_validator
from pydantic import ValidationError as PydanticValidationError

from ..dedup.deduplicator import ContentDeduplicator
from ..extractors.zeromem_extractor import ZeroMemExtractor
from ..graph.persistence import GraphPersistenceService
from ..graph.temporal_store import TemporalStore
from ..indexers.vector import ContextUnitIndexer
from ..models.entities import ContextUnit, Entity, ExtractionResult
from ..resolution.resolver import EntityResolver
from .alert_publisher import AlertPublisher, AnalystAlert
from .stage_publisher import StageEventPublisher


def _assign_temporal_ids(
    tenant_id: str,
    source: str | None,
    now: datetime,
    event_id: str,
) -> tuple[str, str, str, str]:
    # Deterministic bucket IDs derived from ingest metadata, no external state needed
    def _h(key: str) -> str:
        return hashlib.sha256(key.encode()).hexdigest()[:12]

    ts = int(now.timestamp())
    domain = urlparse(source or "").netloc or "unknown"
    session_id = _h(f"{tenant_id}:{now.date().isoformat()}")
    episode_id = _h(f"{tenant_id}:{domain}:{ts // 3600}")
    window_id = _h(f"{tenant_id}:{ts // 900}")
    return session_id, episode_id, window_id, event_id


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------

SCHEMA_VIOLATIONS = Counter(
    "processor_schema_violations_total",
    "Events rejected due to envelope schema validation failures",
)

DEDUP_DROPS = Counter(
    "processor_dedup_drops_total",
    "Events dropped as duplicates by the deduplication layer",
    ["tenant_id"],
)

PIPELINE_STAGE_DURATION = Histogram(
    "processor_pipeline_stage_duration_seconds",
    "Time spent in each pipeline stage",
    ["stage"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

EXTRACTION_CONFIDENCE = Histogram(
    "processor_extraction_confidence",
    "Distribution of NER extraction confidence scores [0, 1]",
    buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
)

CONTEXT_UNITS_CREATED = Counter(
    "processor_context_units_created_total",
    "ContextUnit nodes created and persisted",
    ["tenant_id"],
)


# ---------------------------------------------------------------------------
# Event envelope schema
# ---------------------------------------------------------------------------


class RawEventEnvelope(BaseModel):
    """Minimum-required schema for events arriving on the raw-feed Kafka topic."""

    id: str = ""
    source: str = ""
    tenant_id: str = "default"
    plugin_name: str | None = None
    plugin_version: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "allow"}

    @model_validator(mode="after")
    def validate_payload(self) -> RawEventEnvelope:
        if not self.payload:
            raise ValueError("payload must not be empty")
        required_keys = {"text", "content", "data", "url"}
        if not required_keys.intersection(self.payload.keys()):
            raise ValueError("payload must contain at least one of: text, content, data, url")
        for k, v in self.payload.items():
            if v is None or v == "":
                raise ValueError(f"payload.{k} must not be None or empty string")
        return self


class SchemaViolationError(ValueError):
    """Raised when an incoming Kafka event fails RawEventEnvelope validation → DLQ."""


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class ProcessingPipeline:
    """Orchestrates the V3 Zero-Mem event processing pipeline."""

    def __init__(
        self,
        deduplicator: ContentDeduplicator,
        zeromem_extractor: ZeroMemExtractor,
        vector_indexer: ContextUnitIndexer | None = None,
        temporal_store: TemporalStore | None = None,
        resolver: EntityResolver | None = None,
        graph_persistence: GraphPersistenceService | None = None,
        alert_publisher: AlertPublisher | None = None,
        stage_publisher: StageEventPublisher | None = None,
    ) -> None:
        self._deduplicator = deduplicator
        self._zeromem_extractor = zeromem_extractor
        self._vector_indexer = vector_indexer
        self._temporal_store = temporal_store
        self._resolver = resolver
        self._graph_persistence = graph_persistence
        self._alert_publisher = alert_publisher
        self._stage_publisher = stage_publisher

    async def process(self, event: dict[str, Any]) -> ExtractionResult | None:
        logger.info("pipeline_run_start", extra={"event_id": event.get("id", "")})

        # ── Step 1: Schema validation ──────────────────────────────────────
        if self._stage_publisher:
            self._stage_publisher.publish(
                event.get("id", ""),
                event.get("tenant_id", "default"),
                "schema_validation",
                "active",
            )
        t0 = time.monotonic()
        try:
            envelope = RawEventEnvelope.model_validate(event)
        except PydanticValidationError as exc:
            SCHEMA_VIOLATIONS.inc()
            logger.warning(
                "pipeline_schema_validation_failed",
                extra={"event_id": event.get("id", ""), "error": str(exc)},
            )
            raise SchemaViolationError(str(exc)) from exc
        PIPELINE_STAGE_DURATION.labels(stage="schema_validation").observe(time.monotonic() - t0)
        if self._stage_publisher:
            self._stage_publisher.publish(
                envelope.id, envelope.tenant_id, "schema_validation", "done"
            )

        # ── Step 2: Deduplication ──────────────────────────────────────────
        if self._stage_publisher:
            self._stage_publisher.publish(
                envelope.id, envelope.tenant_id, "deduplication", "active"
            )
        t0 = time.monotonic()
        dedup_result = await self._deduplicator.check_and_set(envelope.tenant_id, event)
        PIPELINE_STAGE_DURATION.labels(stage="deduplication").observe(time.monotonic() - t0)
        if dedup_result.is_duplicate:
            DEDUP_DROPS.labels(tenant_id=envelope.tenant_id).inc()
            logger.info(
                "pipeline_duplicate_event_dropped",
                extra={"event_id": envelope.id, "tenant_id": envelope.tenant_id},
            )
            return None
        if self._stage_publisher:
            self._stage_publisher.publish(envelope.id, envelope.tenant_id, "deduplication", "done")

        # ── Step 3: ZeroMem extraction ─────────────────────────────────────
        if self._stage_publisher:
            self._stage_publisher.publish(
                envelope.id, envelope.tenant_id, "ner_extraction", "active"
            )
        t0 = time.monotonic()
        text: str = str(envelope.payload.get("text") or envelope.payload.get("content", ""))
        now = datetime.now(UTC)
        context_id = f"context--{uuid4()}"

        session_id, episode_id, window_id, turn_id = _assign_temporal_ids(
            envelope.tenant_id, envelope.source, now, envelope.id
        )

        context_unit = ContextUnit(
            id=context_id,
            text=text,
            source_id=envelope.source or None,
            tenant_id=envelope.tenant_id,
            session_id=session_id,
            episode_id=episode_id,
            window_id=window_id,
            turn_id=turn_id,
            created=now,
            metadata={
                "plugin_name": envelope.plugin_name,
                "plugin_version": envelope.plugin_version,
                "source_event_id": envelope.id,
            },
        )

        extraction = self._zeromem_extractor.extract(text, context_id, envelope.tenant_id)
        extraction = extraction.model_copy(
            update={
                "source_event_id": envelope.id,
                "plugin_id": envelope.plugin_name,
                "plugin_version": envelope.plugin_version,
            }
        )
        PIPELINE_STAGE_DURATION.labels(stage="ner_extraction").observe(time.monotonic() - t0)
        EXTRACTION_CONFIDENCE.observe(extraction.extraction_confidence)

        # ── Step 3c: Persist ContextUnit + entity links ────────────────────
        if self._graph_persistence is not None:
            try:
                await self._graph_persistence.upsert_context_unit(context_unit)
                CONTEXT_UNITS_CREATED.labels(tenant_id=envelope.tenant_id).inc()

                # Link adjacent ContextUnits for same source (NEXT_CONTEXT edge)
                if envelope.source:
                    prev_ctx_id = await self._graph_persistence.get_latest_context_for_source(
                        envelope.source, envelope.tenant_id
                    )
                    if prev_ctx_id and prev_ctx_id != context_id:
                        await self._graph_persistence.link_adjacent_contexts(
                            prev_ctx_id, context_id, envelope.tenant_id
                        )
            except Exception:
                logger.exception(
                    "context_unit_persist_failed",
                    extra={"event_id": envelope.id, "context_id": context_id},
                )

        # ── Step 3e: Index ContextUnit in Qdrant (BGE-M3) ─────────────────
        if self._vector_indexer is not None and text.strip():
            try:
                await self._vector_indexer.upsert_to_qdrant(
                    context_id,
                    text,
                    {
                        "source_event_id": envelope.id,
                        "entity_ids": [e.id for e in extraction.entities],
                    },
                    envelope.tenant_id,
                )
            except Exception:
                logger.exception(
                    "vector_index_failed",
                    extra={"event_id": envelope.id, "context_id": context_id},
                )

        # ── Step 3f: Insert temporal record ───────────────────────────────
        if self._temporal_store is not None:
            try:
                await self._temporal_store.insert_context_unit_temporal(context_unit)
                await self._temporal_store.upsert_episode(episode_id, envelope.tenant_id, now)
            except Exception:
                logger.exception(
                    "temporal_insert_failed",
                    extra={"event_id": envelope.id, "context_id": context_id},
                )

        if self._stage_publisher:
            self._stage_publisher.publish(envelope.id, envelope.tenant_id, "ner_extraction", "done")
        logger.info(
            "pipeline_extraction_done",
            extra={
                "event_id": envelope.id,
                "tenant_id": envelope.tenant_id,
                "context_id": context_id,
                "entity_count": len(extraction.entities),
                "confidence": extraction.extraction_confidence,
            },
        )

        # ── Step 4: Entity resolution ──────────────────────────────────────
        if self._resolver is not None:
            if self._stage_publisher:
                self._stage_publisher.publish(
                    envelope.id, envelope.tenant_id, "entity_resolution", "active"
                )
            t0 = time.monotonic()
            resolved_entities: list[Entity] = []
            for entity in extraction.entities:
                entity = entity.model_copy(update={"tenant_id": envelope.tenant_id})
                await self._resolver.resolve_and_persist(envelope.tenant_id, entity)
                resolved_entities.append(entity)

                # Link resolved entity to its ContextUnit
                if self._graph_persistence is not None:
                    weight = extraction.entity_context_weights.get(entity.id, 1.0)
                    try:
                        await self._graph_persistence.link_entity_to_context(
                            entity.id, context_id, envelope.tenant_id, weight
                        )
                    except Exception:
                        logger.exception(
                            "link_entity_to_context_failed",
                            extra={"entity_id": entity.id, "context_id": context_id},
                        )

            PIPELINE_STAGE_DURATION.labels(stage="entity_resolution").observe(time.monotonic() - t0)
            if self._stage_publisher:
                self._stage_publisher.publish(
                    envelope.id, envelope.tenant_id, "entity_resolution", "done"
                )
            extraction = extraction.model_copy(update={"entities": resolved_entities})

        # ── Step 5: Graph persistence ──────────────────────────────────────
        if self._graph_persistence is not None:
            if self._stage_publisher:
                self._stage_publisher.publish(
                    envelope.id, envelope.tenant_id, "graph_persistence", "active"
                )
            t0 = time.monotonic()
            await self._graph_persistence.persist_extraction(extraction, envelope.tenant_id)
            PIPELINE_STAGE_DURATION.labels(stage="graph_persistence").observe(time.monotonic() - t0)
            if self._stage_publisher:
                self._stage_publisher.publish(
                    envelope.id, envelope.tenant_id, "graph_persistence", "done"
                )

        # ── Step 6: Alert publishing ───────────────────────────────────────
        if self._alert_publisher is not None and extraction.extraction_confidence > 0.5:
            if self._stage_publisher:
                self._stage_publisher.publish(
                    envelope.id, envelope.tenant_id, "alert_publishing", "active"
                )
            t0 = time.monotonic()
            n = len(extraction.entities)
            alert = AnalystAlert(
                tenant_id=envelope.tenant_id,
                entity_ids=[e.id for e in extraction.entities],
                summary=f"{n} {'entity' if n == 1 else 'entities'} extracted",
                confidence=extraction.extraction_confidence,
                source_event_id=envelope.id,
            )
            await self._alert_publisher.publish(alert)
            PIPELINE_STAGE_DURATION.labels(stage="alert_publishing").observe(time.monotonic() - t0)
            if self._stage_publisher:
                self._stage_publisher.publish(
                    envelope.id, envelope.tenant_id, "alert_publishing", "done"
                )

        if self._stage_publisher:
            self._stage_publisher.publish(
                envelope.id, envelope.tenant_id, "pipeline_complete", "done"
            )
        logger.info(
            "pipeline_run_done",
            extra={
                "event_id": envelope.id,
                "tenant_id": envelope.tenant_id,
                "confidence": extraction.extraction_confidence,
            },
        )
        return extraction
