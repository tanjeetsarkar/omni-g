from __future__ import annotations

import json
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.stix import ExtractionResult
from src.processor.alert_publisher import (
    ALERT_PUBLISH_ERRORS,
    ALERTS_PUBLISHED,
    AlertPublisher,
    AnalystAlert,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _counter_value(counter: Any, **labels: str) -> float:
    metric = counter.labels(**labels) if labels else counter
    value_obj = getattr(metric, "_value", None)
    if value_obj is None:
        return 0.0
    return float(value_obj.get())


def _make_alert(**overrides: Any) -> AnalystAlert:
    base = dict(
        tenant_id="tenant-test",
        entity_ids=["threat-actor--00000000-0000-0000-0000-000000000001"],
        summary="2 entities extracted",
        confidence=0.8,
        source_event_id="evt-001",
    )
    base.update(overrides)
    return AnalystAlert(**base)


# ---------------------------------------------------------------------------
# AnalystAlert model tests
# ---------------------------------------------------------------------------


class TestAnalystAlertModel:
    def test_alert_model_serialization(self) -> None:
        """model_dump_json() produces valid JSON with all required fields."""
        alert = _make_alert()
        raw = alert.model_dump_json()
        data = json.loads(raw)

        assert "alert_id" in data
        assert data["tenant_id"] == "tenant-test"
        assert isinstance(data["entity_ids"], list)
        assert data["confidence"] == pytest.approx(0.8)
        assert data["source_event_id"] == "evt-001"
        assert "timestamp" in data
        assert "summary" in data

    def test_alert_id_is_uuid4_by_default(self) -> None:
        """Each AnalystAlert gets a unique UUID4 alert_id by default."""
        a1 = _make_alert()
        a2 = _make_alert()
        assert a1.alert_id != a2.alert_id

    def test_community_id_defaults_to_none(self) -> None:
        alert = _make_alert()
        assert alert.community_id is None

    def test_community_id_can_be_set(self) -> None:
        alert = _make_alert(community_id="community-42")
        assert alert.community_id == "community-42"


# ---------------------------------------------------------------------------
# AlertPublisher tests
# ---------------------------------------------------------------------------


class TestAlertPublisher:
    def _make_publisher(self) -> tuple[AlertPublisher, MagicMock]:
        """Return (publisher, mock_producer)."""
        mock_producer = MagicMock()
        with patch("src.processor.alert_publisher.AlertPublisher.__init__", return_value=None):
            publisher = AlertPublisher.__new__(AlertPublisher)
            publisher._topic = "analyst-alerts"
            publisher._producer = mock_producer
        return publisher, mock_producer

    async def test_publishes_alert_above_threshold(self) -> None:
        """publish() calls producer.send() for alerts above confidence threshold."""
        publisher, mock_producer = self._make_publisher()
        alert = _make_alert(confidence=0.8)
        await publisher.publish(alert)
        mock_producer.send.assert_called_once()
        call_args = mock_producer.send.call_args
        assert call_args[0][0] == "analyst-alerts"
        payload = call_args[0][1]
        assert payload["tenant_id"] == "tenant-test"

    async def test_prometheus_counter_increments(self) -> None:
        """ALERTS_PUBLISHED counter increments on successful publish."""
        publisher, mock_producer = self._make_publisher()
        alert = _make_alert(tenant_id="t-counter")
        before = _counter_value(ALERTS_PUBLISHED, tenant_id="t-counter")
        await publisher.publish(alert)
        assert _counter_value(ALERTS_PUBLISHED, tenant_id="t-counter") == before + 1

    async def test_publish_error_increments_error_counter(self) -> None:
        """ALERT_PUBLISH_ERRORS counter increments when producer.send raises."""
        publisher, mock_producer = self._make_publisher()
        mock_producer.send.side_effect = RuntimeError("broker unreachable")
        alert = _make_alert()
        before = _counter_value(ALERT_PUBLISH_ERRORS)
        with pytest.raises(RuntimeError):
            await publisher.publish(alert)
        assert _counter_value(ALERT_PUBLISH_ERRORS) == before + 1

    def test_close_flushes_and_closes_producer(self) -> None:
        """close() calls flush() then close() on the producer."""
        publisher, mock_producer = self._make_publisher()
        publisher.close()
        mock_producer.flush.assert_called_once()
        mock_producer.close.assert_called_once()


# ---------------------------------------------------------------------------
# Pipeline Step 7 integration tests
# ---------------------------------------------------------------------------


class TestPipelineStep7:
    async def test_skips_alert_below_threshold(
        self,
        fake_deduplicator: Any,
        mock_llm_extractor: AsyncMock,
    ) -> None:
        """Pipeline Step 7 does NOT call publisher when confidence <= 0.5."""
        from src.dedup.deduplicator import ContentDeduplicator
        from src.llm.extractor import LLMExtractor
        from src.processor.pipeline import ProcessingPipeline

        mock_llm_extractor.extract.return_value = ExtractionResult(
            source_event_id="evt-low",
            extraction_confidence=0.3,
        )
        mock_publisher = AsyncMock(spec=AlertPublisher)
        pipeline = ProcessingPipeline(
            deduplicator=cast(ContentDeduplicator, fake_deduplicator),
            extractor=cast(LLMExtractor, mock_llm_extractor),
            alert_publisher=cast(AlertPublisher, mock_publisher),
        )
        await pipeline.process({"id": "evt-low", "payload": {"text": "no entities here"}})
        mock_publisher.publish.assert_not_called()

    async def test_publishes_alert_above_threshold(
        self,
        fake_deduplicator: Any,
        mock_llm_extractor: AsyncMock,
    ) -> None:
        """Pipeline Step 7 calls publisher when confidence > 0.5."""
        from src.dedup.deduplicator import ContentDeduplicator
        from src.llm.extractor import LLMExtractor
        from src.processor.pipeline import ProcessingPipeline

        mock_llm_extractor.extract.return_value = ExtractionResult(
            source_event_id="evt-high",
            extraction_confidence=0.9,
        )
        mock_publisher = AsyncMock(spec=AlertPublisher)
        pipeline = ProcessingPipeline(
            deduplicator=cast(ContentDeduplicator, fake_deduplicator),
            extractor=cast(LLMExtractor, mock_llm_extractor),
            alert_publisher=cast(AlertPublisher, mock_publisher),
        )
        await pipeline.process(
            {"id": "evt-high", "tenant_id": "t1", "payload": {"text": "APT28 attacked"}}
        )
        mock_publisher.publish.assert_called_once()
        published_alert: AnalystAlert = mock_publisher.publish.call_args[0][0]
        assert published_alert.tenant_id == "t1"
        assert published_alert.source_event_id == "evt-high"
        assert published_alert.confidence == pytest.approx(0.9)

    async def test_no_publisher_wired_does_not_raise(
        self,
        fake_deduplicator: Any,
        mock_llm_extractor: AsyncMock,
    ) -> None:
        """Pipeline works normally when no AlertPublisher is provided."""
        from src.dedup.deduplicator import ContentDeduplicator
        from src.llm.extractor import LLMExtractor
        from src.processor.pipeline import ProcessingPipeline

        mock_llm_extractor.extract.return_value = ExtractionResult(
            source_event_id="evt-nopub",
            extraction_confidence=0.9,
        )
        pipeline = ProcessingPipeline(
            deduplicator=cast(ContentDeduplicator, fake_deduplicator),
            extractor=cast(LLMExtractor, mock_llm_extractor),
        )
        result = await pipeline.process({"id": "evt-nopub", "payload": {"text": "test"}})
        assert result is not None
