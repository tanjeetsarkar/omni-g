from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from prometheus_client import Counter, Histogram
from pydantic import BaseModel, Field, model_validator
from pydantic import ValidationError as PydanticValidationError

from ..dedup.deduplicator import ContentDeduplicator
from ..graph.persistence import GraphPersistenceService
from ..graphrag.indexer import GraphRAGIndexer
from ..llm.extractor import LLMExtractor
from ..models.entities import (
    CollectedEvidence,
    CredibilityRating,
    Entity,
    ExtractionResult,
    Hypothesis,
    Relationship,
    ReliabilityRating,
    SourceClassification,
)
from ..resolution.resolver import EntityResolver
from .alert_publisher import AlertPublisher, AnalystAlert
from .assessment import AssessmentService
from .assessment_publisher import AssessmentPublisher
from .evidence_publisher import EvidencePublisher
from .hypothesis import HypothesisService
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

EVIDENCE_CREATED = Counter(
    "processor_evidence_created_total",
    "CollectedEvidence objects created from grounded extraction results",
    ["tenant_id"],
)

ASSESSMENTS_PRODUCED = Counter(
    "processor_assessments_produced_total",
    "V2 Assessment objects produced for KIQ-tagged pipeline runs",
    ["tenant_id"],
)

HYPOTHESES_GENERATED = Counter(
    "processor_hypotheses_generated_total",
    "Competing Hypothesis objects generated for KIQ-tagged pipeline runs",
    ["tenant_id"],
)


# ---------------------------------------------------------------------------
# Evidence helpers
# ---------------------------------------------------------------------------


def _build_entity_evidence(
    entity: Entity,
    *,
    tenant_id: str,
    source_event_id: str,
    plugin_id: str | None,
    plugin_version: str | None,
    kiq_id: str | None,
    source_url: str | None,
    source_timestamp: datetime,
) -> CollectedEvidence:
    """Create a :class:`CollectedEvidence` record for a grounded *entity*.

    Source classification defaults to OSINT (public feeds), reliability and
    credibility default to unknown/cannot-be-judged.  The pipeline may enrich
    these later when analyst-grade source metadata is available.
    """
    source_text = entity.source_spans[0].text if entity.source_spans else ""
    assertion = f"{entity.type} '{entity.name}' extracted from source"
    now = datetime.now(UTC)
    return CollectedEvidence(
        id=f"evidence--{uuid4()}",
        tenant_id=tenant_id,
        kiq_id=kiq_id,
        source_event_id=source_event_id,
        plugin_id=plugin_id,
        plugin_version=plugin_version,
        entity_id=entity.id,
        assertion=assertion,
        source_text=source_text,
        source_url=source_url,
        source_timestamp=source_timestamp,
        source_class=SourceClassification.OPEN_SOURCE_INTELLIGENCE,
        source_reliability=ReliabilityRating.UNKNOWN,
        information_credibility=CredibilityRating.CANNOT_BE_JUDGED,
        extraction_confidence=entity.confidence,
        created=now,
        modified=now,
    )


def _build_relationship_evidence(
    rel: Relationship,
    *,
    tenant_id: str,
    source_event_id: str,
    plugin_id: str | None,
    plugin_version: str | None,
    kiq_id: str | None,
    source_url: str | None,
    source_timestamp: datetime,
) -> CollectedEvidence:
    """Create a :class:`CollectedEvidence` record for a grounded *relationship*."""
    assertion = f"Relationship '{rel.type}' from '{rel.source_ref}' to '{rel.target_ref}' extracted"
    now = datetime.now(UTC)
    return CollectedEvidence(
        id=f"evidence--{uuid4()}",
        tenant_id=tenant_id,
        kiq_id=kiq_id,
        source_event_id=source_event_id,
        plugin_id=plugin_id,
        plugin_version=plugin_version,
        relationship_id=rel.id,
        assertion=assertion,
        source_url=source_url,
        source_timestamp=source_timestamp,
        source_class=SourceClassification.OPEN_SOURCE_INTELLIGENCE,
        source_reliability=ReliabilityRating.UNKNOWN,
        information_credibility=CredibilityRating.CANNOT_BE_JUDGED,
        extraction_confidence=rel.confidence,
        created=now,
        modified=now,
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
    # kiq_id carries the Key Intelligence Question reference that tasked this
    # collection. None / absent means the event is untasked (general collection).
    kiq_id: str | None = None

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
        evidence_publisher: EvidencePublisher | None = None,
        assessment_service: AssessmentService | None = None,
        assessment_publisher: AssessmentPublisher | None = None,
        hypothesis_service: HypothesisService | None = None,
        reanalyze_enqueuer: Callable[..., Any] | None = None,
    ) -> None:
        self._deduplicator = deduplicator
        self._extractor = extractor
        self._resolver = resolver
        self._graph_persistence = graph_persistence
        self._graphrag_indexer = graphrag_indexer
        self._alert_publisher = alert_publisher
        self._stage_publisher = stage_publisher
        self._evidence_publisher = evidence_publisher
        self._assessment_service = assessment_service
        self._assessment_publisher = assessment_publisher
        self._hypothesis_service = hypothesis_service
        self._reanalyze_enqueuer = reanalyze_enqueuer

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
        # Stamp KIQ context from the event envelope onto the extraction result so
        # all downstream stages (persistence, alerts, assessments) can trace back
        # to the tasking that motivated collection.
        extraction = extraction.model_copy(update={"kiq_id": envelope.kiq_id})
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

        # ── Step 3.6: Evidence creation ────────────────────────────────────
        # Create CollectedEvidence objects for each grounded entity and
        # relationship, attaching source classification and provenance metadata.
        # Evidence is stamped with the KIQ reference (or None for untasked events).
        source_url: str | None = envelope.payload.get("url") or (
            envelope.source if envelope.source.startswith("http") else None
        )
        raw_ts = envelope.payload.get("published_at") or envelope.payload.get("source_timestamp")
        try:
            source_timestamp: datetime = (
                datetime.fromisoformat(str(raw_ts)) if raw_ts else datetime.now(UTC)
            )
        except (ValueError, TypeError):
            source_timestamp = datetime.now(UTC)

        evidence_list: list[CollectedEvidence] = []
        for entity in grounded_entities:
            evidence_list.append(
                _build_entity_evidence(
                    entity,
                    tenant_id=envelope.tenant_id,
                    source_event_id=envelope.id,
                    plugin_id=envelope.plugin_name,
                    plugin_version=envelope.plugin_version,
                    kiq_id=envelope.kiq_id,
                    source_url=source_url,
                    source_timestamp=source_timestamp,
                )
            )
        for rel in grounded_relationships:
            evidence_list.append(
                _build_relationship_evidence(
                    rel,
                    tenant_id=envelope.tenant_id,
                    source_event_id=envelope.id,
                    plugin_id=envelope.plugin_name,
                    plugin_version=envelope.plugin_version,
                    kiq_id=envelope.kiq_id,
                    source_url=source_url,
                    source_timestamp=source_timestamp,
                )
            )
        extraction = extraction.model_copy(update={"collected_evidence": evidence_list})
        EVIDENCE_CREATED.labels(tenant_id=envelope.tenant_id).inc(len(evidence_list))
        logger.info(
            "pipeline_evidence_created",
            extra={
                "event_id": envelope.id,
                "tenant_id": envelope.tenant_id,
                "kiq_id": envelope.kiq_id,
                "evidence_count": len(evidence_list),
            },
        )

        if self._evidence_publisher is not None:
            for ev in evidence_list:
                await self._evidence_publisher.publish(ev)

        # ── Step 3.7: Hypothesis generation (ACH) ─────────────────────────
        # For KIQ-tagged events with grounded evidence, generate competing
        # hypotheses and perform an ACH scoring pass. The leading hypothesis
        # is retained for the assessment step. A background reanalysis task is
        # also dispatched so deep ACH scoring runs outside the hot path.
        hypotheses: list[Hypothesis] = []
        leading_hypothesis: Hypothesis | None = None
        if self._hypothesis_service is not None and envelope.kiq_id and evidence_list:
            if self._stage_publisher:
                self._stage_publisher.publish(
                    envelope.id, envelope.tenant_id, "hypothesis_generation", "active"
                )
            t0 = time.monotonic()
            logger.info(
                "pipeline_stage_start",
                extra={
                    "stage": "hypothesis_generation",
                    "event_id": envelope.id,
                    "tenant_id": envelope.tenant_id,
                    "kiq_id": envelope.kiq_id,
                    "evidence_count": len(evidence_list),
                },
            )
            hypotheses = await self._hypothesis_service.generate_candidates(
                kiq_id=envelope.kiq_id,
                tenant_id=envelope.tenant_id,
                evidence_list=evidence_list,
            )
            leading_hypothesis = hypotheses[0] if hypotheses else None
            PIPELINE_STAGE_DURATION.labels(stage="hypothesis_generation").observe(
                time.monotonic() - t0
            )
            HYPOTHESES_GENERATED.labels(tenant_id=envelope.tenant_id).inc(len(hypotheses))
            logger.info(
                "pipeline_stage_done",
                extra={
                    "stage": "hypothesis_generation",
                    "event_id": envelope.id,
                    "tenant_id": envelope.tenant_id,
                    "kiq_id": envelope.kiq_id,
                    "hypotheses_count": len(hypotheses),
                    "leading_hypothesis": leading_hypothesis.statement[:120]
                    if leading_hypothesis
                    else None,
                },
            )
            if self._stage_publisher:
                self._stage_publisher.publish(
                    envelope.id, envelope.tenant_id, "hypothesis_generation", "done"
                )
            # Dispatch background reanalysis so full ACH scoring runs outside the
            # hot path without blocking Kafka intake.
            if self._reanalyze_enqueuer is not None and hypotheses:
                try:
                    self._reanalyze_enqueuer(
                        envelope.kiq_id,
                        envelope.tenant_id,
                        [ev.model_dump(mode="json") for ev in evidence_list],
                    )
                    logger.debug(
                        "pipeline_reanalyze_kiq_dispatched",
                        extra={
                            "event_id": envelope.id,
                            "kiq_id": envelope.kiq_id,
                            "tenant_id": envelope.tenant_id,
                        },
                    )
                except Exception as exc:
                    logger.warning(
                        "pipeline_reanalyze_kiq_dispatch_failed",
                        extra={
                            "event_id": envelope.id,
                            "kiq_id": envelope.kiq_id,
                            "error": str(exc),
                        },
                    )
        extraction = extraction.model_copy(update={"hypotheses": hypotheses})

        # ── Step 3.8: Assessment generation ───────────────────────────────
        # For KIQ-tagged events with grounded evidence, generate a first-pass
        # Assessment (BLUF + confidence band + intelligence gaps).
        # Untasked events (kiq_id=None) are skipped; assessment is optional.
        if self._assessment_service is not None and envelope.kiq_id and evidence_list:
            logger.info(
                "pipeline_stage_start",
                extra={
                    "stage": "assessment_generation",
                    "event_id": envelope.id,
                    "tenant_id": envelope.tenant_id,
                    "kiq_id": envelope.kiq_id,
                    "evidence_count": len(evidence_list),
                },
            )
            if self._stage_publisher:
                self._stage_publisher.publish(
                    envelope.id, envelope.tenant_id, "assessment_generation", "active"
                )
            t0 = time.monotonic()
            assessment_result = await self._assessment_service.generate(
                kiq_id=envelope.kiq_id,
                tenant_id=envelope.tenant_id,
                evidence_list=evidence_list,
                leading_hypothesis=leading_hypothesis,
            )
            PIPELINE_STAGE_DURATION.labels(stage="assessment_generation").observe(
                time.monotonic() - t0
            )
            if assessment_result is not None:
                assessment_obj, _gaps = assessment_result
                extraction = extraction.model_copy(update={"assessment": assessment_obj})
                ASSESSMENTS_PRODUCED.labels(tenant_id=envelope.tenant_id).inc()
                logger.info(
                    "pipeline_assessment_produced",
                    extra={
                        "event_id": envelope.id,
                        "tenant_id": envelope.tenant_id,
                        "kiq_id": envelope.kiq_id,
                        "assessment_id": assessment_obj.id,
                        "gaps": len(_gaps),
                        "conclusion_preview": assessment_obj.conclusion[:120],
                    },
                )
                if self._assessment_publisher is not None:
                    await self._assessment_publisher.publish(assessment_obj)
            if self._stage_publisher:
                self._stage_publisher.publish(
                    envelope.id, envelope.tenant_id, "assessment_generation", "done"
                )
            logger.info(
                "pipeline_stage_done",
                extra={
                    "stage": "assessment_generation",
                    "event_id": envelope.id,
                    "tenant_id": envelope.tenant_id,
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
