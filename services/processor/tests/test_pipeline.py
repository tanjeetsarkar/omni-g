from __future__ import annotations

import asyncio
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from prometheus_client import Histogram
from pydantic import ValidationError

from src.dedup.deduplicator import ContentDeduplicator
from src.extractors.zeromem_extractor import ZeroMemExtractor
from src.models.entities import Entity, ExtractionResult
from src.processor.pipeline import (
    DEDUP_DROPS,
    EXTRACTION_CONFIDENCE,
    SCHEMA_VIOLATIONS,
    ProcessingPipeline,
    RawEventEnvelope,
    SchemaViolationError,
)
from src.resolution.resolver import EntityResolver

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _histogram_count(hist: Histogram) -> float:
    """Return the current sample count for a Prometheus Histogram (no labels)."""
    for family in hist.collect():
        for sample in family.samples:
            if sample.name.endswith("_count"):
                return sample.value
    return 0.0


def _counter_value(counter: Any, **labels: str) -> float:
    metric = counter.labels(**labels) if labels else counter
    value_obj = getattr(metric, "_value", None)
    if value_obj is None:
        return 0.0
    return float(value_obj.get())


def _make_valid_event(**overrides: Any) -> dict[str, Any]:
    """Return a minimal valid raw event, with optional field overrides."""
    base: dict[str, Any] = {
        "id": "evt-001",
        "tenant_id": "tenant1",
        "payload": {"text": "APT28 attacked critical infrastructure"},
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_extractor() -> MagicMock:
    """ZeroMemExtractor mock returning a fixed ExtractionResult (no LLM calls)."""
    mock = MagicMock()
    mock.extract.return_value = ExtractionResult(
        source_event_id="evt-001",
        entities=[],
        relationships=[],
        extraction_confidence=0.75,
    )
    return mock


@pytest.fixture()
async def pipeline(
    fake_deduplicator: ContentDeduplicator,
    mock_extractor: MagicMock,
) -> ProcessingPipeline:
    return ProcessingPipeline(
        deduplicator=fake_deduplicator,
        zeromem_extractor=cast(ZeroMemExtractor, mock_extractor),
    )


# ---------------------------------------------------------------------------
# RawEventEnvelope validation tests
# ---------------------------------------------------------------------------


class TestRawEventEnvelope:
    def test_valid_event_parses_correctly(self) -> None:
        envelope = RawEventEnvelope.model_validate(_make_valid_event())
        assert envelope.id == "evt-001"
        assert envelope.tenant_id == "tenant1"
        assert envelope.payload["text"] == "APT28 attacked critical infrastructure"

    def test_defaults_applied_for_optional_fields(self) -> None:
        envelope = RawEventEnvelope.model_validate({"payload": {"text": "intel"}})
        assert envelope.id == ""
        assert envelope.tenant_id == "default"
        assert envelope.plugin_name is None

    def test_empty_payload_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError, match="empty"):
            RawEventEnvelope.model_validate({"payload": {}})

    def test_payload_without_content_key_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError, match="text, content, data, url"):
            RawEventEnvelope.model_validate({"payload": {"ip": "1.2.3.4"}})

    def test_payload_with_none_value_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            RawEventEnvelope.model_validate({"payload": {"text": None}})

    def test_payload_with_empty_string_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            RawEventEnvelope.model_validate({"payload": {"text": ""}})

    def test_url_is_a_valid_content_key(self) -> None:
        envelope = RawEventEnvelope.model_validate({"payload": {"url": "https://example.com"}})
        assert envelope.payload["url"] == "https://example.com"

    def test_data_is_a_valid_content_key(self) -> None:
        envelope = RawEventEnvelope.model_validate({"payload": {"data": "raw binary blob"}})
        assert envelope.payload["data"] == "raw binary blob"

    def test_content_is_a_valid_content_key(self) -> None:
        envelope = RawEventEnvelope.model_validate({"payload": {"content": "article text"}})
        assert envelope.payload["content"] == "article text"

    def test_extra_top_level_fields_are_allowed(self) -> None:
        envelope = RawEventEnvelope.model_validate({"payload": {"text": "intel"}, "custom_field": "value"})
        assert envelope.model_extra is not None
        assert envelope.model_extra.get("custom_field") == "value"

    def test_plugin_fields_propagated(self) -> None:
        envelope = RawEventEnvelope.model_validate(
            {
                "payload": {"text": "intel"},
                "plugin_name": "twitter-mcp",
                "plugin_version": "1.2.3",
            }
        )
        assert envelope.plugin_name == "twitter-mcp"
        assert envelope.plugin_version == "1.2.3"


# ---------------------------------------------------------------------------
# ProcessingPipeline tests
# ---------------------------------------------------------------------------


class TestProcessingPipeline:
    async def test_happy_path_returns_extraction_result(
        self,
        pipeline: ProcessingPipeline,
        mock_extractor: MagicMock,
    ) -> None:
        """Valid event flows through the pipeline and returns an ExtractionResult."""
        result = await pipeline.process(_make_valid_event())
        assert result is not None
        assert isinstance(result, ExtractionResult)
        mock_extractor.extract.assert_called_once()

    async def test_schema_violation_raises_schema_violation_error(
        self,
        pipeline: ProcessingPipeline,
        mock_extractor: MagicMock,
    ) -> None:
        """Event with empty payload raises SchemaViolationError; extractor not called."""
        bad_event: dict[str, Any] = {"id": "evt-bad", "payload": {}}
        with pytest.raises(SchemaViolationError):
            await pipeline.process(bad_event)
        mock_extractor.extract.assert_not_called()

    async def test_schema_violation_increments_metric(
        self,
        pipeline: ProcessingPipeline,
    ) -> None:
        """Each schema violation increments the SCHEMA_VIOLATIONS counter."""
        before = _counter_value(SCHEMA_VIOLATIONS)
        bad_event: dict[str, Any] = {"payload": {"ip": "1.2.3.4"}}
        with pytest.raises(SchemaViolationError):
            await pipeline.process(bad_event)
        assert _counter_value(SCHEMA_VIOLATIONS) == before + 1

    async def test_missing_payload_raises_schema_violation_error(
        self,
        pipeline: ProcessingPipeline,
    ) -> None:
        """Event with no payload key at all raises SchemaViolationError."""
        with pytest.raises(SchemaViolationError):
            await pipeline.process({"id": "evt-no-payload"})

    async def test_duplicate_event_returns_none(
        self,
        pipeline: ProcessingPipeline,
        mock_extractor: MagicMock,
    ) -> None:
        """Sending the same event twice: first is processed, second is dropped."""
        event = _make_valid_event()
        first = await pipeline.process(event)
        second = await pipeline.process(event)
        assert first is not None
        assert second is None
        # LLM extractor called only once
        assert mock_extractor.extract.call_count == 1

    async def test_duplicate_drop_increments_dedup_metric(
        self,
        pipeline: ProcessingPipeline,
    ) -> None:
        """DEDUP_DROPS counter increments once per duplicate drop."""
        event = _make_valid_event(
            id="evt-dedup-metric",
            tenant_id="t-metric",
            payload={"text": "dedup metric test"},
        )
        await pipeline.process(event)
        before = _counter_value(DEDUP_DROPS, tenant_id="t-metric")
        await pipeline.process(event)  # duplicate
        assert _counter_value(DEDUP_DROPS, tenant_id="t-metric") == before + 1

    async def test_confidence_histogram_observed_on_success(
        self,
        pipeline: ProcessingPipeline,
        mock_extractor: MagicMock,
    ) -> None:
        """EXTRACTION_CONFIDENCE histogram count increments after a successful extraction."""
        mock_extractor.extract.return_value = ExtractionResult(
            source_event_id="evt-conf",
            entities=[],
            extraction_confidence=0.8,
        )
        event = _make_valid_event(id="evt-conf", payload={"text": "confidence histogram test"})
        before = _histogram_count(EXTRACTION_CONFIDENCE)
        await pipeline.process(event)
        assert _histogram_count(EXTRACTION_CONFIDENCE) == before + 1

    async def test_confidence_histogram_not_observed_on_duplicate(
        self,
        pipeline: ProcessingPipeline,
        mock_extractor: MagicMock,
    ) -> None:
        """Duplicates are dropped before extraction; no confidence observation recorded."""
        mock_extractor.extract.return_value = ExtractionResult(
            source_event_id="evt-dup-conf",
            entities=[],
            extraction_confidence=0.75,
        )
        event = _make_valid_event(
            id="evt-dup-conf",
            payload={"text": "dup conf test"},
        )
        await pipeline.process(event)  # first — succeeds
        before = _histogram_count(EXTRACTION_CONFIDENCE)
        await pipeline.process(event)  # second — duplicate, dropped
        assert _histogram_count(EXTRACTION_CONFIDENCE) == before  # no new observation

    async def test_text_payload_passed_to_extractor(
        self,
        pipeline: ProcessingPipeline,
        mock_extractor: MagicMock,
    ) -> None:
        """The 'text' payload value is forwarded as the text argument to the extractor."""
        event = _make_valid_event(
            id="evt-text",
            payload={"text": "APT-X launched a cyberattack"},
        )
        await pipeline.process(event)
        text_arg = mock_extractor.extract.call_args.args[0]
        assert text_arg == "APT-X launched a cyberattack"

    async def test_content_key_used_as_text_fallback(
        self,
        pipeline: ProcessingPipeline,
        mock_extractor: MagicMock,
    ) -> None:
        """When 'text' is absent, 'content' value is forwarded to the extractor."""
        event = _make_valid_event(
            id="evt-content",
            payload={"content": "threat intel report body"},
        )
        await pipeline.process(event)
        text_arg = mock_extractor.extract.call_args.args[0]
        assert text_arg == "threat intel report body"

    async def test_plugin_metadata_forwarded(
        self,
        pipeline: ProcessingPipeline,
        mock_extractor: MagicMock,
    ) -> None:
        """plugin_name and plugin_version are forwarded and copied into the extraction result."""
        event = _make_valid_event(
            id="evt-meta",
            plugin_name="shodan-mcp",
            plugin_version="2.0.0",
        )
        result = await pipeline.process(event)
        assert result is not None
        assert result.plugin_id == "shodan-mcp"
        assert result.plugin_version == "2.0.0"

    async def test_different_tenants_not_deduplicated(
        self,
        pipeline: ProcessingPipeline,
        mock_extractor: MagicMock,
    ) -> None:
        """Same payload content under different tenant IDs must each be processed."""
        event_t1 = _make_valid_event(id="evt-iso", tenant_id="tenant-A")
        event_t2 = _make_valid_event(id="evt-iso", tenant_id="tenant-B")
        r1 = await pipeline.process(event_t1)
        r2 = await pipeline.process(event_t2)
        assert r1 is not None
        assert r2 is not None
        assert mock_extractor.extract.call_count == 2

    async def test_multiple_workers_share_deduplicator(
        self,
        fake_deduplicator: ContentDeduplicator,
        mock_extractor: MagicMock,
    ) -> None:
        """Two worker pipelines sharing the same deduplicator drop cross-worker duplicates."""
        pipeline1 = ProcessingPipeline(
            deduplicator=fake_deduplicator,
            zeromem_extractor=cast(ZeroMemExtractor, mock_extractor),
        )
        pipeline2 = ProcessingPipeline(
            deduplicator=fake_deduplicator,
            zeromem_extractor=cast(ZeroMemExtractor, mock_extractor),
        )
        event1 = _make_valid_event(id="evt-w1", payload={"text": "worker1 unique event"})
        event2 = _make_valid_event(id="evt-w2", payload={"text": "worker2 unique event"})
        r1, r2 = await asyncio.gather(
            pipeline1.process(event1),
            pipeline2.process(event2),
        )
        assert r1 is not None
        assert r2 is not None
        assert mock_extractor.extract.call_count == 2

    async def test_resolver_called_for_each_entity_when_provided(
        self,
        fake_deduplicator: ContentDeduplicator,
        mock_extractor: MagicMock,
    ) -> None:
        """When a resolver is wired in, resolve_and_persist is called once per extracted entity."""
        from datetime import UTC, datetime

        now = datetime.now(UTC)

        # Build a result with two generic entities so we can count calls
        entity1 = Entity(
            id="entity--00000000-0000-0000-0000-000000000001",
            type="ThreatActor",
            name="APT28",
            created=now,
            modified=now,
        )
        entity2 = Entity(
            id="entity--00000000-0000-0000-0000-000000000002",
            type="Malware",
            name="Emotet",
            created=now,
            modified=now,
        )
        mock_extractor.extract.return_value = ExtractionResult(
            source_event_id="evt-resolver",
            extraction_confidence=0.9,
            entities=[entity1, entity2],
        )

        mock_resolver = AsyncMock(spec=EntityResolver)
        pipeline_with_resolver = ProcessingPipeline(
            deduplicator=fake_deduplicator,
            zeromem_extractor=cast(ZeroMemExtractor, mock_extractor),
            resolver=cast(EntityResolver, mock_resolver),
        )

        event = _make_valid_event(id="evt-resolver", payload={"text": "APT28 dropped Emotet"})
        result = await pipeline_with_resolver.process(event)

        assert result is not None
        # resolve_and_persist should be called once for each entity (2 total)
        assert mock_resolver.resolve_and_persist.call_count == 2

    async def test_resolver_canonical_ids_propagated_to_extraction_result(
        self,
        fake_deduplicator: ContentDeduplicator,
        mock_extractor: MagicMock,
    ) -> None:
        """When resolver returns AUTO_MERGE with a different ID, canonical IDs replace originals."""
        from datetime import UTC, datetime

        from src.resolution.models import ResolutionDecision, ResolutionResult

        now = datetime.now(UTC)
        original_id = "entity--00000000-0000-0000-0000-000000000001"
        canonical_id = "entity--aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

        entity1 = Entity(
            id=original_id,
            type="Person",
            name="Narendra Modi",
            created=now,
            modified=now,
        )
        mock_extractor.extract.return_value = ExtractionResult(
            source_event_id="evt-canonical",
            extraction_confidence=0.9,
            entities=[entity1],
        )

        mock_resolver = AsyncMock(spec=EntityResolver)

        # Return AUTO_MERGE with a matched_entity_id different from the incoming id
        mock_resolver.resolve_and_persist.return_value = ResolutionResult(
            decision=ResolutionDecision.AUTO_MERGE,
            matched_entity_id=canonical_id,
            confidence_score=0.97,
            entity=entity1,
        )

        mock_graph = AsyncMock()
        pipeline_with_resolver = ProcessingPipeline(
            deduplicator=fake_deduplicator,
            zeromem_extractor=cast(ZeroMemExtractor, mock_extractor),
            resolver=cast(EntityResolver, mock_resolver),
            graph_persistence=mock_graph,
        )

        event = _make_valid_event(id="evt-canonical", payload={"text": "Narendra Modi speaks"})
        result = await pipeline_with_resolver.process(event)

        assert result is not None
        # The entity in the result should carry the canonical ID, not the original
        assert len(result.entities) == 1
        assert result.entities[0].id == canonical_id
        # persist_extraction should have been called with the canonical ID
        mock_graph.persist_extraction.assert_called_once()
        persisted = mock_graph.persist_extraction.call_args.args[0]
        assert persisted.entities[0].id == canonical_id

    async def test_resolver_dedups_entities_mapped_to_same_canonical_id(
        self,
        fake_deduplicator: ContentDeduplicator,
        mock_extractor: MagicMock,
    ) -> None:
        """When two incoming entities merge to the same canonical ID, the result is deduped."""
        from datetime import UTC, datetime

        from src.resolution.models import ResolutionDecision, ResolutionResult

        now = datetime.now(UTC)
        canonical_id = "entity--aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

        entity1 = Entity(
            id="entity--00000000-0000-0000-0000-000000000001",
            type="Person",
            name="PM Modi",
            confidence=0.75,
            created=now,
            modified=now,
        )
        entity2 = Entity(
            id="entity--00000000-0000-0000-0000-000000000002",
            type="Person",
            name="Narendra Modi",
            confidence=0.95,
            created=now,
            modified=now,
        )
        mock_extractor.extract.return_value = ExtractionResult(
            source_event_id="evt-dedup",
            extraction_confidence=0.9,
            entities=[entity1, entity2],
        )

        mock_resolver = AsyncMock(spec=EntityResolver)

        # Both entities AUTO_MERGE to the same canonical ID
        mock_resolver.resolve_and_persist.return_value = ResolutionResult(
            decision=ResolutionDecision.AUTO_MERGE,
            matched_entity_id=canonical_id,
            confidence_score=0.97,
            entity=entity1,
        )

        mock_graph = AsyncMock()
        pipeline_with_resolver = ProcessingPipeline(
            deduplicator=fake_deduplicator,
            zeromem_extractor=cast(ZeroMemExtractor, mock_extractor),
            resolver=cast(EntityResolver, mock_resolver),
            graph_persistence=mock_graph,
        )

        event = _make_valid_event(id="evt-dedup", payload={"text": "PM Modi speaks"})
        result = await pipeline_with_resolver.process(event)

        assert result is not None
        # Dedup should collapse to 1 entity, keeping the highest-confidence replica.
        # entity2 (Narendra Modi, 0.95) has higher confidence than entity1 (PM Modi, 0.75).
        assert len(result.entities) == 1
        assert result.entities[0].id == canonical_id
        assert result.entities[0].name == "Narendra Modi"
        assert result.entities[0].confidence == 0.95

    async def test_resolver_not_called_when_none(
        self,
        pipeline: ProcessingPipeline,
    ) -> None:
        """When no resolver is wired in (None), the pipeline still completes successfully."""
        # The default `pipeline` fixture has no resolver; just verify it doesn't raise
        result = await pipeline.process(_make_valid_event(id="evt-no-resolver"))
        assert result is not None

    async def test_schema_violation_error_does_not_reach_deduplicator(
        self,
        fake_deduplicator: ContentDeduplicator,
        mock_extractor: MagicMock,
    ) -> None:
        """Schema validation failure short-circuits before dedup; Redis not written."""
        pipeline = ProcessingPipeline(
            deduplicator=fake_deduplicator,
            zeromem_extractor=cast(ZeroMemExtractor, mock_extractor),
        )
        bad_event: dict[str, Any] = {"payload": {}}
        with pytest.raises(SchemaViolationError):
            await pipeline.process(bad_event)
        # The same event sent again should NOT be detected as a duplicate (was never stored)
        with pytest.raises(SchemaViolationError):
            await pipeline.process(bad_event)
