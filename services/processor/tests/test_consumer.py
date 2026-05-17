from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

from src.dedup.deduplicator import ContentDeduplicator
from src.kafka.consumer import RawEventConsumer


def _make_mock_message(value: dict[str, Any]) -> MagicMock:
    msg = MagicMock()
    msg.value = value
    msg.partition = 0
    msg.offset = 0
    return msg


def _make_consumer(topic: str = "raw-feed") -> RawEventConsumer:
    return RawEventConsumer(
        brokers="localhost:9092",
        topic=topic,
        group_id="test-group",
    )


class TestProcessMessages:
    async def test_happy_path_handler_called_and_committed(self) -> None:
        """process_messages calls handler for each message and commits offset."""
        consumer = _make_consumer()

        msg = _make_mock_message({"id": "evt-001", "payload": {"text": "hello"}})
        mock_kafka = MagicMock()
        mock_kafka.__iter__ = MagicMock(return_value=iter([msg]))
        consumer._consumer = mock_kafka
        consumer._producer = MagicMock()

        handler = AsyncMock()
        await consumer.process_messages(handler)

        handler.assert_called_once_with(msg.value)
        mock_kafka.commit.assert_called_once()

    async def test_dlq_on_handler_exception(self) -> None:
        """When handler raises, message goes to DLQ, offset is committed, nothing re-raised."""
        consumer = _make_consumer()

        msg = _make_mock_message({"id": "evt-002", "payload": {"text": "bad event"}})
        mock_kafka = MagicMock()
        mock_kafka.__iter__ = MagicMock(return_value=iter([msg]))
        consumer._consumer = mock_kafka
        mock_producer = MagicMock()
        consumer._producer = mock_producer

        handler = AsyncMock(side_effect=ValueError("processing failed"))
        await consumer.process_messages(handler)

        # DLQ send must have been called with the DLQ topic as first arg
        mock_producer.send.assert_called_once()
        assert mock_producer.send.call_args[0][0] == "raw-feed.dlq"

        # Offset must still be committed even on failure
        mock_kafka.commit.assert_called_once()

    async def test_dedup_integration_second_event_dropped(
        self,
        fake_deduplicator: ContentDeduplicator,
    ) -> None:
        """Two identical events → handler called only once (dedup drops the second)."""
        consumer = _make_consumer()

        event: dict[str, Any] = {
            "id": "evt-003",
            "tenant_id": "t1",
            "payload": {"text": "duplicate text"},
        }
        msg1 = _make_mock_message(event)
        msg2 = _make_mock_message(event)  # identical payload

        mock_kafka = MagicMock()
        mock_kafka.__iter__ = MagicMock(return_value=iter([msg1, msg2]))
        consumer._consumer = mock_kafka
        consumer._producer = MagicMock()

        handler = AsyncMock()

        async def handle_with_dedup(event_dict: dict[str, Any]) -> None:
            tenant_id = event_dict.get("tenant_id", "default")
            result = await fake_deduplicator.check_and_set(tenant_id, event_dict)
            if result.is_duplicate:
                return
            await handler(event_dict)

        await consumer.process_messages(handle_with_dedup)

        # Handler invoked exactly once — second message was a duplicate
        handler.assert_called_once_with(event)
        # Both offsets committed (dedup drop is not an error)
        assert mock_kafka.commit.call_count == 2

    async def test_schema_violation_sent_to_dlq_with_correct_error_type(self) -> None:
        """SchemaViolationError from the pipeline handler → DLQ payload carries error_type."""
        from src.processor.pipeline import SchemaViolationError

        consumer = _make_consumer()

        msg = _make_mock_message({"id": "evt-schema-bad", "payload": {}})
        mock_kafka = MagicMock()
        mock_kafka.__iter__ = MagicMock(return_value=iter([msg]))
        consumer._consumer = mock_kafka
        mock_producer = MagicMock()
        consumer._producer = mock_producer

        handler = AsyncMock(side_effect=SchemaViolationError("payload must not be empty"))
        await consumer.process_messages(handler)

        # The message must land in the DLQ
        mock_producer.send.assert_called_once()
        dlq_topic = mock_producer.send.call_args[0][0]
        dlq_payload = mock_producer.send.call_args[0][1]
        assert dlq_topic == "raw-feed.dlq"
        assert dlq_payload["error_type"] == "SchemaViolationError"

        # Offset is committed even for schema violations so the consumer makes progress
        mock_kafka.commit.assert_called_once()
