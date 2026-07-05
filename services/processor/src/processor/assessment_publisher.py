"""V2 Step 7 — Assessment Kafka publisher.

Publishes :class:`~src.models.entities.Assessment` objects as
``assessment.produced`` events to a dedicated Kafka topic.  Follows the same
pattern as :class:`~src.processor.evidence_publisher.EvidencePublisher`.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from prometheus_client import Counter

from ..models.entities import Assessment

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------

ASSESSMENT_PUBLISHED = Counter(
    "processor_assessment_published_total",
    "Total assessment.produced events successfully published to Kafka",
    ["tenant_id"],
)

ASSESSMENT_PUBLISH_ERRORS = Counter(
    "processor_assessment_publish_errors_total",
    "Total errors while publishing assessment events to Kafka",
)


# ---------------------------------------------------------------------------
# Publisher
# ---------------------------------------------------------------------------


class AssessmentPublisher:
    """Publishes :class:`~src.models.entities.Assessment` as ``assessment.produced`` Kafka events.

    Uses ``kafka-python-ng``'s synchronous ``KafkaProducer`` (non-blocking send
    via a background thread) so it integrates cleanly with the async pipeline.
    """

    def __init__(self, brokers: str, topic: str) -> None:
        from kafka import KafkaProducer

        self._topic = topic
        logger.info("Initialising AssessmentPublisher", extra={"topic": topic, "brokers": brokers})
        self._producer: Any = KafkaProducer(
            bootstrap_servers=brokers.split(","),
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )

    async def publish(self, assessment: Assessment) -> None:
        """Serialize *assessment* to JSON and send it to the configured Kafka topic."""
        try:
            payload = json.loads(assessment.model_dump_json())
            logger.debug(
                "assessment_publish_payload",
                extra={"topic": self._topic, "assessment_id": assessment.id},
            )
            self._producer.send(self._topic, payload)
            ASSESSMENT_PUBLISHED.labels(tenant_id=assessment.tenant_id).inc()
            logger.info(
                "assessment_published",
                extra={
                    "topic": self._topic,
                    "assessment_id": assessment.id,
                    "kiq_id": assessment.kiq_id,
                    "tenant_id": assessment.tenant_id,
                },
            )
        except Exception as exc:
            ASSESSMENT_PUBLISH_ERRORS.inc()
            logger.error(
                "assessment_publish_error",
                extra={"error_type": type(exc).__name__, "error": str(exc)},
            )

    def close(self) -> None:
        """Flush pending messages and close the producer."""
        try:
            self._producer.flush()
            self._producer.close()
        except Exception as exc:
            logger.warning("assessment_publisher_close_error", extra={"error": str(exc)})
