from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from neo4j import AsyncDriver, AsyncGraphDatabase
from qdrant_client import AsyncQdrantClient

from ..dedup.deduplicator import ContentDeduplicator
from ..graph.persistence import GraphPersistenceService
from ..graph.schema import GraphSchemaManager
from ..graphrag.community import CommunityDetector
from ..graphrag.indexer import GraphRAGIndexer
from ..graphrag.summarizer import CommunitySummarizer
from ..llm.extractor import LLMExtractor
from ..resolution.resolver import EntityResolver
from .alert_publisher import AlertPublisher
from .assessment import AssessmentService
from .assessment_publisher import AssessmentPublisher
from .config import Settings
from .evidence_publisher import EvidencePublisher
from .hypothesis import HypothesisService
from .pipeline import ProcessingPipeline
from .stage_publisher import StageEventPublisher

logger = logging.getLogger(__name__)


@dataclass
class ProcessorRuntime:
    pipeline: ProcessingPipeline
    deduplicator: ContentDeduplicator
    neo4j_driver: AsyncDriver
    qdrant_client: AsyncQdrantClient
    alert_publisher: AlertPublisher
    stage_publisher: StageEventPublisher
    evidence_publisher: EvidencePublisher
    assessment_publisher: AssessmentPublisher

    @classmethod
    async def create(cls, cfg: Settings, *, worker_id: int) -> ProcessorRuntime:
        logger.info(
            "Initialising processor worker dependencies",
            extra={
                "worker_id": worker_id,
                "kafka_raw_topic": cfg.kafka_raw_topic,
                "kafka_dlq_topic": cfg.kafka_dlq_topic,
                "kafka_alerts_topic": cfg.kafka_alerts_topic,
                "kafka_evidence_topic": cfg.kafka_evidence_topic,
                "kafka_processor_events_topic": cfg.kafka_processor_events_topic,
                "redis_url": cfg.redis_url,
                "neo4j_url": cfg.neo4j_url,
                "qdrant_url": cfg.qdrant_url,
            },
        )

        deduplicator = ContentDeduplicator(ttl_seconds=cfg.dedup_ttl_seconds)
        await deduplicator.connect(cfg.redis_url)
        logger.info("Deduplicator connected", extra={"worker_id": worker_id})

        extractor = LLMExtractor()
        logger.info("LLM extractor initialised", extra={"worker_id": worker_id})

        neo4j_driver = AsyncGraphDatabase.driver(
            cfg.neo4j_url,
            auth=(cfg.neo4j_user, cfg.neo4j_password),
        )
        qdrant_client = AsyncQdrantClient(
            url=cfg.qdrant_url,
            api_key=cfg.qdrant_api_key,
        )
        resolver = EntityResolver(neo4j_driver=neo4j_driver, qdrant_client=qdrant_client)
        logger.info("EntityResolver initialised", extra={"worker_id": worker_id})

        schema_manager = GraphSchemaManager(neo4j_driver)
        try:
            await schema_manager.initialize()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Graph schema initialization failed (continuing)",
                extra={"error": str(exc), "worker_id": worker_id},
            )

        graph_persistence = GraphPersistenceService(neo4j_driver)
        logger.info("GraphPersistenceService initialised", extra={"worker_id": worker_id})

        community_detector = CommunityDetector(neo4j_driver)
        summarizer = CommunitySummarizer(
            neo4j_driver,
            ollama_url=cfg.ollama_url,
            model=cfg.ollama_model,
            openai_api_key=cfg.openai_api_key,
        )
        graphrag_indexer = GraphRAGIndexer(community_detector, summarizer)
        logger.info("GraphRAG indexer initialised", extra={"worker_id": worker_id})

        alert_publisher = AlertPublisher(
            brokers=cfg.kafka_brokers,
            topic=cfg.kafka_alerts_topic,
        )
        evidence_publisher = EvidencePublisher(
            brokers=cfg.kafka_brokers,
            topic=cfg.kafka_evidence_topic,
        )
        assessment_service = AssessmentService()
        assessment_publisher = AssessmentPublisher(
            brokers=cfg.kafka_brokers,
            topic=cfg.kafka_assessment_topic,
        )
        hypothesis_service = HypothesisService()
        stage_publisher = StageEventPublisher(
            brokers=cfg.kafka_brokers,
            topic=cfg.kafka_processor_events_topic,
        )

        # Late import to avoid circular dependency: tasks → runtime → pipeline
        from .tasks import enqueue_reanalyze_kiq  # noqa: PLC0415

        pipeline = ProcessingPipeline(
            deduplicator=deduplicator,
            extractor=extractor,
            resolver=resolver,
            graph_persistence=graph_persistence,
            graphrag_indexer=graphrag_indexer,
            alert_publisher=alert_publisher,
            stage_publisher=stage_publisher,
            evidence_publisher=evidence_publisher,
            assessment_service=assessment_service,
            assessment_publisher=assessment_publisher,
            hypothesis_service=hypothesis_service,
            reanalyze_enqueuer=enqueue_reanalyze_kiq,
        )

        logger.info(
            "Processor runtime initialised",
            extra={
                "worker_id": worker_id,
                "neo4j_url": cfg.neo4j_url,
                "qdrant_url": cfg.qdrant_url,
            },
        )

        return cls(
            pipeline=pipeline,
            deduplicator=deduplicator,
            neo4j_driver=neo4j_driver,
            qdrant_client=qdrant_client,
            alert_publisher=alert_publisher,
            stage_publisher=stage_publisher,
            evidence_publisher=evidence_publisher,
            assessment_publisher=assessment_publisher,
        )

    async def process_event(self, event: dict[str, Any]) -> None:
        await self.pipeline.process(event)

    async def close(self) -> None:
        await self.deduplicator.close()
        await self.neo4j_driver.close()
        await self.qdrant_client.close()
        self.alert_publisher.close()
        self.stage_publisher.close()
        self.assessment_publisher.close()
