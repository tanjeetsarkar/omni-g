from __future__ import annotations

import json
import logging
from typing import Any

from prometheus_client import Counter

from ..models.entities import CollectedEvidence

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------

EVIDENCE_PUBLISHED = Counter(
    "processor_evidence_published_total",
    "Total evidence.created events successfully published to Kafka",
    ["tenant_id"],
)

EVIDENCE_PUBLISH_ERRORS = Counter(
    "processor_evidence_publish_errors_total",
    "Total errors while publishing evidence events to Kafka",
)


# ---------------------------------------------------------------------------
# Publisher
# ---------------------------------------------------------------------------


class EvidencePublisher:
    """Publishes :class:`CollectedEvidence` objects as ``evidence.created`` Kafka events.

    Follows the same pattern as :class:`~src.processor.alert_publisher.AlertPublisher`:
    uses ``kafka-python-ng``'s synchronous ``KafkaProducer`` (non-blocking send via
    a background thread) so it integrates cleanly with the async pipeline.
    """

    def __init__(self, brokers: str, topic: str) -> None:
        from kafka import KafkaProducer

        self._topic = topic
        logger.info("Initialising EvidencePublisher", extra={"topic": topic, "brokers": brokers})
        self._producer: Any = KafkaProducer(
            bootstrap_servers=brokers.split(","),
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )

    async def publish(self, evidence: CollectedEvidence) -> None:
        """Serialize *evidence* to JSON and send it to the configured Kafka topic."""
        try:
            payload = json.loads(evidence.model_dump_json())
            logger.debug(
                "evidence_publish_payload",
                extra={"topic": self._topic, "evidence_id": evidence.id},
            )
            self._producer.send(self._topic, payload)
            EVIDENCE_PUBLISHED.labels(tenant_id=evidence.tenant_id).inc()
            logger.info(
                "evidence_published",
                extra={
                    "evidence_id": evidence.id,
                    "tenant_id": evidence.tenant_id,
                    "kiq_id": evidence.kiq_id,
                    "topic": self._topic,
                },
            )
        except Exception as exc:  # noqa: BLE001
            EVIDENCE_PUBLISH_ERRORS.inc()
            logger.error(
                "evidence_publish_failed",
                extra={"evidence_id": evidence.id, "error": str(exc)},
            )
            raise

    def close(self) -> None:
        """Flush pending messages and close the underlying producer."""
        logger.info("Closing EvidencePublisher", extra={"topic": self._topic})
        self._producer.flush()
        self._producer.close()
