from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable, Iterator
from typing import Any

from prometheus_client import Counter, Histogram

from kafka import KafkaConsumer, KafkaProducer

logger = logging.getLogger(__name__)

EVENTS_CONSUMED = Counter(
    "processor_events_consumed_total",
    "Events consumed from Kafka",
    ["topic", "status"],
)
PROCESSING_LATENCY = Histogram(
    "processor_processing_latency_seconds",
    "End-to-end processing latency per message",
    ["topic"],
)
DLQ_EVENTS = Counter(
    "processor_dlq_events_total",
    "Messages sent to the dead-letter queue",
    ["reason"],
)


class RawEventConsumer:
    """
    Consumes raw events from the `raw-feed` Kafka topic.

    Provides:
    - Consumer group with manual offset commit (at-least-once semantics)
    - Rebalance callbacks (assign / revoke)
    - Dead-letter queue for failed messages
    - Prometheus metrics (events consumed, processing latency, DLQ sends)
    """

    def __init__(
        self,
        brokers: str,
        topic: str,
        group_id: str,
        dlq_topic: str = "raw-feed.dlq",
    ) -> None:
        self._brokers = brokers
        self._topic = topic
        self._group_id = group_id
        self._dlq_topic = dlq_topic
        self._consumer: KafkaConsumer | None = None
        self._producer: KafkaProducer | None = None

    # ------------------------------------------------------------------
    # Rebalance callbacks
    # ------------------------------------------------------------------

    def _on_assign(self, consumer: Any, partitions: list[Any]) -> None:
        logger.info(
            "Kafka partitions assigned",
            extra={"partitions": [str(p) for p in partitions]},
        )

    def _on_revoke(self, consumer: Any, partitions: list[Any]) -> None:
        logger.info(
            "Kafka partitions revoked",
            extra={"partitions": [str(p) for p in partitions]},
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Connect to Kafka, create the DLQ producer, and begin subscribing."""
        self._producer = KafkaProducer(
            bootstrap_servers=self._brokers.split(","),
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )
        self._consumer = KafkaConsumer(
            bootstrap_servers=self._brokers.split(","),
            group_id=self._group_id,
            auto_offset_reset="earliest",
            enable_auto_commit=False,
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        )
        self._consumer.subscribe([self._topic])
        logger.info(
            "Kafka consumer started",
            extra={"topic": self._topic, "group_id": self._group_id},
        )

    def stop(self) -> None:
        """Close consumer and producer gracefully."""
        if self._consumer is not None:
            self._consumer.close()
            self._consumer = None
            logger.info("Kafka consumer closed")
        if self._producer is not None:
            self._producer.close()
            self._producer = None

    def close(self) -> None:
        """Backward-compatible alias for stop()."""
        self.stop()

    # ------------------------------------------------------------------
    # Message iteration
    # ------------------------------------------------------------------

    def messages(self) -> Iterator[dict[str, Any]]:
        """Yield deserialized event dicts from the topic (synchronous)."""
        if self._consumer is None:
            raise RuntimeError("Consumer not started — call start() first")
        for msg in self._consumer:
            yield msg.value
            self._consumer.commit()

    async def process_messages(
        self,
        handler: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        """Consume messages and dispatch to *handler*, with metrics and DLQ.

        For each message:
        - Times the full handling with PROCESSING_LATENCY
        - On success: commits offset, increments EVENTS_CONSUMED[status=success]
        - On Exception: sends original message to DLQ, commits offset,
          increments DLQ_EVENTS and EVENTS_CONSUMED[status=dlq]

        Terminates cleanly on KeyboardInterrupt or asyncio.CancelledError,
        calling stop() before re-raising.
        """
        if self._consumer is None:
            raise RuntimeError("Consumer not started — call start() first")
        try:
            for msg in self._consumer:
                with PROCESSING_LATENCY.labels(topic=self._topic).time():
                    try:
                        await handler(msg.value)
                        self._consumer.commit()
                        EVENTS_CONSUMED.labels(topic=self._topic, status="success").inc()
                    except Exception as exc:
                        await self._send_to_dlq(msg, exc)
                        self._consumer.commit()
                        DLQ_EVENTS.labels(reason=type(exc).__name__).inc()
                        EVENTS_CONSUMED.labels(topic=self._topic, status="dlq").inc()
        except (KeyboardInterrupt, asyncio.CancelledError):
            self.stop()
            raise

    # ------------------------------------------------------------------
    # DLQ helper
    # ------------------------------------------------------------------

    async def _send_to_dlq(self, msg: Any, exc: Exception) -> None:
        """Serialize the failed message plus error info and send to the DLQ topic."""
        if self._producer is None:
            logger.error(
                "DLQ producer not initialised — dropping failed message",
                extra={"error_type": type(exc).__name__, "error": str(exc)},
            )
            return
        dlq_payload = {
            "original_message": msg.value,
            "error": str(exc),
            "error_type": type(exc).__name__,
            "topic": self._topic,
            "partition": msg.partition,
            "offset": msg.offset,
        }
        self._producer.send(self._dlq_topic, dlq_payload)
        logger.warning(
            "Event sent to DLQ",
            extra={"dlq_topic": self._dlq_topic, "error_type": type(exc).__name__},
        )
