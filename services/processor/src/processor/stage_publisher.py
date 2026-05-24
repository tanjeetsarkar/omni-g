from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class StageEvent(BaseModel):
    event_id: str
    tenant_id: str
    stage: str
    status: Literal["active", "done"]
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class StageEventPublisher:
    """Fire-and-forget publisher for pipeline stage progress events.

    Sends lightweight ``StageEvent`` messages to a Kafka topic (default:
    ``processor-events``) so the delivery gateway can broadcast real-time
    pipeline visibility to connected UI clients.

    Errors are logged but never re-raised — stage instrumentation must never
    interrupt the processing pipeline.
    """

    def __init__(self, brokers: str, topic: str) -> None:
        from kafka import KafkaProducer

        self._topic = topic
        self._producer: Any = KafkaProducer(
            bootstrap_servers=brokers.split(","),
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )

    def publish(
        self,
        event_id: str,
        tenant_id: str,
        stage: str,
        status: Literal["active", "done"],
    ) -> None:
        """Enqueue a stage event. Never raises."""
        try:
            ev = StageEvent(
                event_id=event_id,
                tenant_id=tenant_id,
                stage=stage,
                status=status,
            )
            self._producer.send(self._topic, json.loads(ev.model_dump_json()))
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "stage_event_publish_failed",
                extra={"stage": stage, "status": status, "error": str(exc)},
            )

    def close(self) -> None:
        self._producer.close()
