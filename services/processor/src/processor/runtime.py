"""ProcessorRuntime — initialises all service connections for a worker process."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from neo4j import AsyncDriver, AsyncGraphDatabase
from qdrant_client import AsyncQdrantClient

from ..dedup.deduplicator import ContentDeduplicator
from ..extractors.zeromem_extractor import ZeroMemExtractor
from ..graph.persistence import GraphPersistenceService
from ..graph.schema import GraphSchemaManager
from ..graph.temporal_store import TemporalStore
from ..indexers.vector import ContextUnitIndexer
from ..resolution.resolver import EntityResolver
from .alert_publisher import AlertPublisher
from .config import Settings
from .pipeline import ProcessingPipeline
from .stage_publisher import StageEventPublisher

logger = logging.getLogger(__name__)


def _parse_allowed_labels(labels_str: str) -> frozenset[str] | None:
    """Parse a comma-separated *labels_str* into a frozenset, or ``None`` if empty.

    Returns ``None`` (meaning "use the module-level default") when *labels_str*
    is empty or whitespace-only.
    """
    stripped = labels_str.strip()
    if not stripped:
        return None
    return frozenset(lbl.strip() for lbl in stripped.split(",") if lbl.strip())


@dataclass
class ProcessorRuntime:
    pipeline: ProcessingPipeline
    deduplicator: ContentDeduplicator
    neo4j_driver: AsyncDriver
    qdrant_client: AsyncQdrantClient
    vector_indexer: ContextUnitIndexer
    temporal_store: TemporalStore
    alert_publisher: AlertPublisher
    stage_publisher: StageEventPublisher

    @classmethod
    async def create(cls, cfg: Settings, *, worker_id: int) -> ProcessorRuntime:
        logger.info("Initialising processor worker dependencies", extra={"worker_id": worker_id})

        deduplicator = ContentDeduplicator(ttl_seconds=cfg.dedup_ttl_seconds)
        await deduplicator.connect(cfg.redis_url)
        logger.debug("Deduplicator connected", extra={"worker_id": worker_id})

        zeromem_extractor = ZeroMemExtractor(
            spacy_allowed_labels=_parse_allowed_labels(cfg.extractor_spacy_allowed_labels),
            min_entity_length=cfg.extractor_min_entity_length,
        )

        neo4j_driver = AsyncGraphDatabase.driver(
            cfg.neo4j_url,
            auth=(cfg.neo4j_user, cfg.neo4j_password),
        )
        qdrant_client = AsyncQdrantClient(
            url=cfg.qdrant_url,
            api_key=cfg.qdrant_api_key,
        )
        resolver = EntityResolver(neo4j_driver=neo4j_driver, qdrant_client=qdrant_client)

        schema_manager = GraphSchemaManager(neo4j_driver)
        try:
            await schema_manager.initialize()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Graph schema initialization failed (continuing)",
                extra={"error": str(exc), "worker_id": worker_id},
            )

        graph_persistence = GraphPersistenceService(neo4j_driver)

        vector_indexer = ContextUnitIndexer(
            qdrant_url=cfg.qdrant_url,
            api_key=cfg.qdrant_api_key,
            settings=cfg,
        )

        temporal_store = TemporalStore(postgres_url=cfg.postgres_url)
        try:
            await temporal_store.connect()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "TemporalStore connection failed (continuing without temporal hierarchy)",
                extra={"error": str(exc), "worker_id": worker_id},
            )

        alert_publisher = AlertPublisher(
            brokers=cfg.kafka_brokers,
            topic=cfg.kafka_alerts_topic,
        )
        stage_publisher = StageEventPublisher(
            brokers=cfg.kafka_brokers,
            topic=cfg.kafka_processor_events_topic,
        )

        pipeline = ProcessingPipeline(
            deduplicator=deduplicator,
            zeromem_extractor=zeromem_extractor,
            vector_indexer=vector_indexer,
            temporal_store=temporal_store,
            resolver=resolver,
            graph_persistence=graph_persistence,
            alert_publisher=alert_publisher,
            stage_publisher=stage_publisher,
        )

        logger.info(
            "Processor runtime initialised",
            extra={
                "worker_id": worker_id,
                "llm_provider": cfg.llm_provider,
                "neo4j_url": cfg.neo4j_url,
                "qdrant_url": cfg.qdrant_url,
            },
        )

        return cls(
            pipeline=pipeline,
            deduplicator=deduplicator,
            neo4j_driver=neo4j_driver,
            qdrant_client=qdrant_client,
            vector_indexer=vector_indexer,
            temporal_store=temporal_store,
            alert_publisher=alert_publisher,
            stage_publisher=stage_publisher,
        )

    async def process_event(self, event: dict[str, Any]) -> None:
        # Extract search_id from the event envelope so pipeline stage/alert
        # events carry the correlation ID back to the Delivery UI.
        search_id = event.get("search_id") or None
        await self.pipeline.process(event, search_id=search_id)

    async def close(self) -> None:
        await self.deduplicator.close()
        await self.neo4j_driver.close()
        await self.qdrant_client.close()
        await self.vector_indexer.close()
        await self.temporal_store.close()
        self.alert_publisher.close()
        self.stage_publisher.close()
