from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from prometheus_client import Counter
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------

ALERTS_PUBLISHED = Counter(
    "processor_alerts_published_total",
    "Total analyst alerts successfully published to Kafka",
    ["tenant_id"],
)

ALERT_PUBLISH_ERRORS = Counter(
    "processor_alert_publish_errors_total",
    "Total errors while publishing analyst alerts to Kafka",
)


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


class AnalystAlert(BaseModel):
    """Alert model published to the analyst-alerts Kafka topic."""

    alert_id: str = Field(default_factory=lambda: str(uuid4()))
    tenant_id: str
    entity_ids: list[str] = Field(default_factory=list)
    community_id: str | None = None
    summary: str
    confidence: float
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source_event_id: str


# ---------------------------------------------------------------------------
# Publisher
# ---------------------------------------------------------------------------


class AlertPublisher:
    """Publishes :class:`AnalystAlert` objects to a Kafka topic.

    Uses ``kafka-python-ng``'s synchronous ``KafkaProducer`` under the hood
    (its ``send()`` call is non-blocking—it enqueues messages in a background
    thread) so it integrates cleanly with the async pipeline.
    """

    def __init__(self, brokers: str, topic: str) -> None:
        from kafka import KafkaProducer

        self._topic = topic
        self._producer: Any = KafkaProducer(
            bootstrap_servers=brokers.split(","),
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )

    async def publish(self, alert: AnalystAlert) -> None:
        """Serialize *alert* to JSON and send it to the configured Kafka topic."""
        try:
            payload = json.loads(alert.model_dump_json())
            self._producer.send(self._topic, payload)
            ALERTS_PUBLISHED.labels(tenant_id=alert.tenant_id).inc()
            logger.info(
                "alert_published",
                extra={
                    "alert_id": alert.alert_id,
                    "tenant_id": alert.tenant_id,
                    "topic": self._topic,
                    "confidence": alert.confidence,
                },
            )
        except Exception as exc:  # noqa: BLE001
            ALERT_PUBLISH_ERRORS.inc()
            logger.error(
                "alert_publish_failed",
                extra={"alert_id": alert.alert_id, "error": str(exc)},
            )
            raise

    def close(self) -> None:
        """Flush pending messages and close the underlying producer."""
        self._producer.flush()
        self._producer.close()
