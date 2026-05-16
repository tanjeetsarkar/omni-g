from __future__ import annotations

import json
import logging
from typing import Any, Iterator

from kafka import KafkaConsumer  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)


class RawEventConsumer:
    """
    Consumes raw events from the `raw-feed` Kafka topic.

    Phase M3.4 implementation will add dead-letter queue handling,
    consumer group rebalancing callbacks, and Prometheus metrics.
    This skeleton provides the interface contract.
    """

    def __init__(
        self,
        brokers: str,
        topic: str,
        group_id: str,
    ) -> None:
        self._brokers = brokers
        self._topic = topic
        self._group_id = group_id
        self._consumer: KafkaConsumer | None = None

    def start(self) -> None:
        """Connect to Kafka and begin subscribing."""
        self._consumer = KafkaConsumer(
            self._topic,
            bootstrap_servers=self._brokers.split(","),
            group_id=self._group_id,
            auto_offset_reset="earliest",
            enable_auto_commit=False,
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        )
        logger.info(
            "Kafka consumer started",
            extra={"topic": self._topic, "group_id": self._group_id},
        )

    def messages(self) -> Iterator[dict[str, Any]]:
        """Yield deserialized event dicts from the topic."""
        if self._consumer is None:
            raise RuntimeError("Consumer not started — call start() first")
        for msg in self._consumer:
            yield msg.value
            self._consumer.commit()

    def close(self) -> None:
        if self._consumer is not None:
            self._consumer.close()
            logger.info("Kafka consumer closed")
