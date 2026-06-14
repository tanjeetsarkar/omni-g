from __future__ import annotations

import logging
import time
from typing import Any

from prometheus_client import Counter, Histogram
from pydantic import BaseModel, Field, model_validator
from pydantic import ValidationError as PydanticValidationError

from ..dedup.deduplicator import ContentDeduplicator
from ..graph.persistence import GraphPersistenceService
from ..graphrag.indexer import GraphRAGIndexer
from ..llm.extractor import LLMExtractor
from ..models.entities import Entity, ExtractionResult
from ..resolution.resolver import EntityResolver
from .alert_publisher import AlertPublisher, AnalystAlert
from .stage_publisher import StageEventPublisher

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------

EXTRACTION_CONFIDENCE = Histogram(
    "processor_extraction_confidence",
    "Distribution of LLM extraction confidence scores [0, 1]",
    buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
)

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

GROUNDING_REJECTIONS = Counter(
    "processor_grounding_rejections_total",
    "Extracted artifacts rejected by the source-grounding validation gate",
    ["tenant_id", "reason"],
)


# ---------------------------------------------------------------------------
# Event envelope schema
# ---------------------------------------------------------------------------


class RawEventEnvelope(BaseModel):
    """Minimum-required schema for events arriving on the raw-feed Kafka topic.

    Validation rules (mirror the /validate sidecar endpoint):
    - ``payload`` must be non-empty
    - ``payload`` must contain at least one of: text, content, data, url
    - No top-level payload key may be None or an empty string

    Extra fields are allowed so the aggregator can attach arbitrary metadata.
    """

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


# ---------------------------------------------------------------------------
# Exception type
# ---------------------------------------------------------------------------


class SchemaViolationError(ValueError):
    """Raised when an incoming Kafka event fails RawEventEnvelope validation.

    The Kafka consumer catches this and routes the message to the DLQ with
    ``error_type=SchemaViolationError`` in the DLQ payload.
    """


def _is_entity_grounded(entity: Entity, source_text: str) -> bool:
    """Return True if *entity* is explicitly mentioned in *source_text*.

    Checks LLM-supplied source_spans first (preferred: verbatim excerpt that
    the LLM cited), then falls back to a case-insensitive substring match on
    the entity name.  Entities named 'Unknown' or with empty names are
    rejected.  If source_text is empty the entity is passed through (no text
    to check against).
    """
    if not source_text:
        return True  # Cannot validate without source text; pass through
    # Preferred: check LLM-supplied evidence spans
    for span in entity.source_spans:
        if span.text and span.text.lower() in source_text.lower():
            return True
    # Fallback: case-insensitive name match
    name = (entity.name or "").strip()
    if name.lower() in ("", "unknown"):
        return False
    return name.lower() in source_text.lower()


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class ProcessingPipeline:
    """Orchestrates the full event processing pipeline.

    Stages
    ------
    1. **Schema validation** — validates the event envelope; raises
       :exc:`SchemaViolationError` on failure so the consumer routes it to DLQ.
    2. **Deduplication** — checks Redis; silently drops duplicate events.
    3. **LLM entity extraction** — extracts STIX entities from event text and
       records an :metric:`processor_extraction_confidence` histogram observation.
    4. **Entity resolution** — resolves extracted STIX entities against the knowledge
       graph via vector blocking (Qdrant) and structural matching (Neo4j).
    5. **Graph persistence** — transactionally writes all STIX entities and
       relationships from the extraction result to Neo4j.
    6. **GraphRAG incremental index** — re-runs community detection on the 2-hop
       subgraph around each newly persisted entity and regenerates summaries.
    7. **Alert publishing** — if an :class:`AlertPublisher` is wired in and the
       extraction confidence exceeds 0.5, publishes an :class:`AnalystAlert` to
       the ``analyst-alerts`` Kafka topic.

    Returns
    -------
    :class:`~src.models.stix.ExtractionResult`
        When the event was processed successfully.
    ``None``
        When the event was silently dropped as a duplicate.

    Raises
    ------
    :exc:`SchemaViolationError`
        When the event fails envelope validation (→ DLQ).
    """

    def __init__(
        self,
        deduplicator: ContentDeduplicator,
        extractor: LLMExtractor,
        resolver: EntityResolver | None = None,
        graph_persistence: GraphPersistenceService | None = None,
        graphrag_indexer: GraphRAGIndexer | None = None,
        alert_publisher: AlertPublisher | None = None,
        stage_publisher: StageEventPublisher | None = None,
    ) -> None:
        self._deduplicator = deduplicator
        self._extractor = extractor
        self._resolver = resolver
        self._graph_persistence = graph_persistence
        self._graphrag_indexer = graphrag_indexer
        self._alert_publisher = alert_publisher
        self._stage_publisher = stage_publisher

    async def process(self, event: dict[str, Any]) -> ExtractionResult | None:
        logger.info("pipeline_run_start", extra={"event_id": event.get("id", "")})
        logger.debug("pipeline_input_event", extra={"event": event})

        # ── Step 1: Schema validation ──────────────────────────────────────
        logger.info(
            "pipeline_stage_start",
            extra={"stage": "schema_validation", "event_id": event.get("id", "")},
        )
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
        logger.info(
            "pipeline_stage_done",
            extra={
                "stage": "schema_validation",
                "event_id": envelope.id,
                "tenant_id": envelope.tenant_id,
            },
        )

        # ── Step 2: Deduplication ──────────────────────────────────────────
        logger.info(
            "pipeline_stage_start",
            extra={
                "stage": "deduplication",
                "event_id": envelope.id,
                "tenant_id": envelope.tenant_id,
            },
        )
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
        logger.info(
            "pipeline_stage_done",
            extra={
                "stage": "deduplication",
                "event_id": envelope.id,
                "tenant_id": envelope.tenant_id,
            },
        )

        # ── Step 3: LLM entity extraction ─────────────────────────────────
        logger.info(
            "pipeline_stage_start",
            extra={
                "stage": "llm_extraction",
                "event_id": envelope.id,
                "tenant_id": envelope.tenant_id,
            },
        )
        if self._stage_publisher:
            self._stage_publisher.publish(
                envelope.id, envelope.tenant_id, "llm_extraction", "active"
            )
        t0 = time.monotonic()
        text: str = str(envelope.payload.get("text") or envelope.payload.get("content", ""))
        metadata: dict[str, Any] = {
            "plugin_name": envelope.plugin_name,
            "plugin_version": envelope.plugin_version,
            "source_type": envelope.payload.get("source_type", "general"),
        }
        extraction = await self._extractor.extract(envelope.id, text, metadata)
        logger.debug(
            "pipeline_extraction_payload",
            extra={
                "event_id": envelope.id,
                "tenant_id": envelope.tenant_id,
                "extraction": extraction.model_dump(mode="json"),
            },
        )
        PIPELINE_STAGE_DURATION.labels(stage="llm_extraction").observe(time.monotonic() - t0)
        if self._stage_publisher:
            self._stage_publisher.publish(envelope.id, envelope.tenant_id, "llm_extraction", "done")
        EXTRACTION_CONFIDENCE.observe(extraction.extraction_confidence)
        logger.info(
            "pipeline_stage_done",
            extra={
                "stage": "llm_extraction",
                "event_id": envelope.id,
                "tenant_id": envelope.tenant_id,
                "entities": len(extraction.entities),
                "confidence": extraction.extraction_confidence,
            },
        )

        # ── Step 3.5: Grounding validation ────────────────────────────────
        # Reject entities not explicitly present in the raw source text so
        # LLM hallucinations never enter the Knowledge Graph.  Relationships
        # whose endpoints are rejected are also dropped.
        logger.info(
            "pipeline_stage_start",
            extra={
                "stage": "grounding_validation",
                "event_id": envelope.id,
                "tenant_id": envelope.tenant_id,
            },
        )
        if self._stage_publisher:
            self._stage_publisher.publish(
                envelope.id, envelope.tenant_id, "grounding_validation", "active"
            )
        t0 = time.monotonic()
        grounded_entities: list[Entity] = []
        rejected_entity_ids: set[str] = set()
        for entity in extraction.entities:
            if _is_entity_grounded(entity, text):
                grounded_entities.append(entity)
            else:
                rejected_entity_ids.add(entity.id)
                logger.warning(
                    "pipeline_grounding_rejected",
                    extra={
                        "event_id": envelope.id,
                        "tenant_id": envelope.tenant_id,
                        "entity_name": entity.name,
                        "entity_type": entity.type,
                        "entity_id": entity.id,
                    },
                )
        grounded_relationships = [
            r
            for r in extraction.relationships
            if r.source_ref not in rejected_entity_ids and r.target_ref not in rejected_entity_ids
        ]
        rejected_entity_count = len(extraction.entities) - len(grounded_entities)
        rejected_rel_count = len(extraction.relationships) - len(grounded_relationships)
        if rejected_entity_count > 0:
            GROUNDING_REJECTIONS.labels(tenant_id=envelope.tenant_id, reason="not_in_source").inc(
                rejected_entity_count
            )
        if rejected_rel_count > 0:
            GROUNDING_REJECTIONS.labels(
                tenant_id=envelope.tenant_id, reason="endpoint_not_grounded"
            ).inc(rejected_rel_count)
        extraction = extraction.model_copy(
            update={"entities": grounded_entities, "relationships": grounded_relationships}
        )
        PIPELINE_STAGE_DURATION.labels(stage="grounding_validation").observe(time.monotonic() - t0)
        if self._stage_publisher:
            self._stage_publisher.publish(
                envelope.id, envelope.tenant_id, "grounding_validation", "done"
            )
        logger.info(
            "pipeline_stage_done",
            extra={
                "stage": "grounding_validation",
                "event_id": envelope.id,
                "tenant_id": envelope.tenant_id,
                "grounded_entities": len(grounded_entities),
                "rejected_entities": rejected_entity_count,
                "rejected_relationships": rejected_rel_count,
            },
        )

        # ── Step 4: Entity resolution ──────────────────────────────────────
        if self._resolver is not None:
            logger.info(
                "pipeline_stage_start",
                extra={
                    "stage": "entity_resolution",
                    "event_id": envelope.id,
                    "tenant_id": envelope.tenant_id,
                },
            )
            if self._stage_publisher:
                self._stage_publisher.publish(
                    envelope.id, envelope.tenant_id, "entity_resolution", "active"
                )
            t0 = time.monotonic()
            for entity in extraction.entities:
                logger.debug(
                    "pipeline_entity_resolution_input",
                    extra={
                        "event_id": envelope.id,
                        "tenant_id": envelope.tenant_id,
                        "entity": entity.model_dump(mode="json"),
                    },
                )
                await self._resolver.resolve_and_persist(envelope.tenant_id, entity)
            PIPELINE_STAGE_DURATION.labels(stage="entity_resolution").observe(time.monotonic() - t0)
            logger.info(
                "pipeline_stage_done",
                extra={
                    "stage": "entity_resolution",
                    "event_id": envelope.id,
                    "tenant_id": envelope.tenant_id,
                },
            )
            if self._stage_publisher:
                self._stage_publisher.publish(
                    envelope.id, envelope.tenant_id, "entity_resolution", "done"
                )

        # ── Step 5: Graph persistence ──────────────────────────────────────
        if self._graph_persistence is not None:
            logger.info(
                "pipeline_stage_start",
                extra={
                    "stage": "graph_persistence",
                    "event_id": envelope.id,
                    "tenant_id": envelope.tenant_id,
                },
            )
            if self._stage_publisher:
                self._stage_publisher.publish(
                    envelope.id, envelope.tenant_id, "graph_persistence", "active"
                )
            t0 = time.monotonic()
            await self._graph_persistence.persist_extraction(extraction, envelope.tenant_id)
            logger.debug(
                "pipeline_graph_persistence_payload",
                extra={
                    "event_id": envelope.id,
                    "tenant_id": envelope.tenant_id,
                    "extraction": extraction.model_dump(mode="json"),
                },
            )
            PIPELINE_STAGE_DURATION.labels(stage="graph_persistence").observe(time.monotonic() - t0)
            logger.info(
                "pipeline_stage_done",
                extra={
                    "stage": "graph_persistence",
                    "event_id": envelope.id,
                    "tenant_id": envelope.tenant_id,
                },
            )
            if self._stage_publisher:
                self._stage_publisher.publish(
                    envelope.id, envelope.tenant_id, "graph_persistence", "done"
                )

        # ── Step 6: GraphRAG incremental index ────────────────────────────
        if self._graphrag_indexer is not None:
            logger.info(
                "pipeline_stage_start",
                extra={
                    "stage": "graphrag_index",
                    "event_id": envelope.id,
                    "tenant_id": envelope.tenant_id,
                },
            )
            if self._stage_publisher:
                self._stage_publisher.publish(
                    envelope.id, envelope.tenant_id, "graphrag_index", "active"
                )
            t0 = time.monotonic()
            for entity_id in [e.id for e in extraction.entities]:
                logger.debug(
                    "pipeline_graphrag_incremental_input",
                    extra={
                        "event_id": envelope.id,
                        "tenant_id": envelope.tenant_id,
                        "entity_id": entity_id,
                    },
                )
                await self._graphrag_indexer.index_incremental(entity_id, envelope.tenant_id)
            PIPELINE_STAGE_DURATION.labels(stage="graphrag_index").observe(time.monotonic() - t0)
            logger.info(
                "pipeline_stage_done",
                extra={
                    "stage": "graphrag_index",
                    "event_id": envelope.id,
                    "tenant_id": envelope.tenant_id,
                },
            )
            if self._stage_publisher:
                self._stage_publisher.publish(
                    envelope.id, envelope.tenant_id, "graphrag_index", "done"
                )

        # ── Step 7: Alert publishing ───────────────────────────────────────
        if self._alert_publisher is not None and extraction.extraction_confidence > 0.5:
            logger.info(
                "pipeline_stage_start",
                extra={
                    "stage": "alert_publishing",
                    "event_id": envelope.id,
                    "tenant_id": envelope.tenant_id,
                },
            )
            if self._stage_publisher:
                self._stage_publisher.publish(
                    envelope.id, envelope.tenant_id, "alert_publishing", "active"
                )
            t0 = time.monotonic()
            summary_text: str
            if hasattr(extraction, "summary_text"):
                summary_text = str(getattr(extraction, "summary_text", ""))[:500]
            else:
                n = len(extraction.entities)
                summary_text = f"{n} {'entity' if n == 1 else 'entities'} extracted"
            alert = AnalystAlert(
                tenant_id=envelope.tenant_id,
                entity_ids=[e.id for e in extraction.entities],
                summary=summary_text,
                confidence=extraction.extraction_confidence,
                source_event_id=envelope.id,
            )
            logger.debug(
                "pipeline_alert_payload",
                extra={
                    "event_id": envelope.id,
                    "tenant_id": envelope.tenant_id,
                    "alert": alert.model_dump(mode="json"),
                },
            )
            await self._alert_publisher.publish(alert)
            PIPELINE_STAGE_DURATION.labels(stage="alert_publishing").observe(time.monotonic() - t0)
            if self._stage_publisher:
                self._stage_publisher.publish(
                    envelope.id, envelope.tenant_id, "alert_publishing", "done"
                )
            logger.info(
                "pipeline_stage_done",
                extra={
                    "stage": "alert_publishing",
                    "event_id": envelope.id,
                    "tenant_id": envelope.tenant_id,
                },
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
