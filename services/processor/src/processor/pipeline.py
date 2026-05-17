from __future__ import annotations

import logging
from typing import Any

from prometheus_client import Counter, Histogram
from pydantic import BaseModel, Field, model_validator
from pydantic import ValidationError as PydanticValidationError

from ..dedup.deduplicator import ContentDeduplicator
from ..llm.extractor import LLMExtractor
from ..models.stix import ExtractionResult
from ..resolution.resolver import EntityResolver

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
            raise ValueError(
                "payload must contain at least one of: text, content, data, url"
            )
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


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class ProcessingPipeline:
    """Orchestrates the full M3.4 event processing pipeline.

    Stages
    ------
    1. **Schema validation** — validates the event envelope; raises
       :exc:`SchemaViolationError` on failure so the consumer routes it to DLQ.
    2. **Deduplication** — checks Redis; silently drops duplicate events.
    3. **LLM entity extraction** — extracts STIX entities from event text and
       records an :metric:`processor_extraction_confidence` histogram observation.
    4. **Entity resolution** — resolves extracted STIX entities against the knowledge
       graph via vector blocking (Qdrant) and structural matching (Neo4j).

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
    ) -> None:
        self._deduplicator = deduplicator
        self._extractor = extractor
        self._resolver = resolver

    async def process(self, event: dict[str, Any]) -> ExtractionResult | None:
        # ── Step 1: Schema validation ──────────────────────────────────────
        try:
            envelope = RawEventEnvelope.model_validate(event)
        except PydanticValidationError as exc:
            SCHEMA_VIOLATIONS.inc()
            raise SchemaViolationError(str(exc)) from exc

        # ── Step 2: Deduplication ──────────────────────────────────────────
        dedup_result = await self._deduplicator.check_and_set(envelope.tenant_id, event)
        if dedup_result.is_duplicate:
            DEDUP_DROPS.labels(tenant_id=envelope.tenant_id).inc()
            logger.debug(
                "Duplicate event dropped",
                extra={"event_id": envelope.id, "tenant_id": envelope.tenant_id},
            )
            return None

        # ── Step 3: LLM entity extraction ─────────────────────────────────
        text: str = str(
            envelope.payload.get("text") or envelope.payload.get("content", "")
        )
        metadata: dict[str, Any] = {
            "plugin_name": envelope.plugin_name,
            "plugin_version": envelope.plugin_version,
        }
        extraction = await self._extractor.extract(envelope.id, text, metadata)

        EXTRACTION_CONFIDENCE.observe(extraction.extraction_confidence)
        logger.info(
            "extraction_complete",
            extra={
                "event_id": envelope.id,
                "tenant_id": envelope.tenant_id,
                "entities": len(extraction.threat_actors) + len(extraction.malware),
                "confidence": extraction.extraction_confidence,
            },
        )

        # ── Step 4: Entity resolution ──────────────────────────────────────
        if self._resolver is not None:
            for entity in extraction.all_entities():
                await self._resolver.resolve_and_persist(envelope.tenant_id, entity)

        return extraction
