from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

from prometheus_client import Counter, Gauge, Histogram

from .community import CommunityDetector, CommunityResult
from .summarizer import CommunitySummarizer

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------

GRAPHRAG_INDEX_LATENCY = Histogram(
    "processor_graphrag_index_latency_seconds",
    "Latency of GraphRAG indexing runs",
    ["tenant_id", "mode"],
    buckets=[0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0],
)

GRAPHRAG_COMMUNITIES_TOTAL = Gauge(
    "processor_graphrag_communities_total",
    "Total number of communities detected in the last indexing run",
    ["tenant_id"],
)

GRAPHRAG_SUMMARIES_UPDATED = Counter(
    "processor_graphrag_summaries_updated_total",
    "Total community summaries written to graph nodes",
    ["tenant_id"],
)

GRAPHRAG_UPDATE_FREQUENCY = Counter(
    "processor_graphrag_update_frequency_total",
    "Total number of GraphRAG index runs triggered",
    ["tenant_id"],
)


# ---------------------------------------------------------------------------
# Data transfer object
# ---------------------------------------------------------------------------


@dataclass
class IndexingResult:
    """Outcome of one GraphRAG indexing pass."""

    tenant_id: str
    communities_detected: int
    summaries_generated: int
    duration_seconds: float
    incremental: bool
    completed_at: datetime = field(default_factory=lambda: datetime.now(UTC))


# ---------------------------------------------------------------------------
# GraphRAGIndexer
# ---------------------------------------------------------------------------


class GraphRAGIndexer:
    """Orchestrate community detection and summary generation.

    Supports both full re-indexing and incremental indexing for a single
    entity (2-hop subgraph only).
    """

    def __init__(
        self,
        community_detector: CommunityDetector,
        summarizer: CommunitySummarizer,
    ) -> None:
        self._detector = community_detector
        self._summarizer = summarizer
        self._background_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def index_full(self, tenant_id: str) -> IndexingResult:
        """Detect all communities for *tenant_id* and generate summaries.

        Returns an :class:`IndexingResult` describing the run.
        """
        t0 = time.perf_counter()
        GRAPHRAG_UPDATE_FREQUENCY.labels(tenant_id=tenant_id).inc()

        communities = await self._detector.detect_communities(tenant_id)
        summaries_generated = await self._summarize_and_store(communities, tenant_id)

        duration = time.perf_counter() - t0
        GRAPHRAG_INDEX_LATENCY.labels(tenant_id=tenant_id, mode="full").observe(duration)
        GRAPHRAG_COMMUNITIES_TOTAL.labels(tenant_id=tenant_id).set(len(communities))

        result = IndexingResult(
            tenant_id=tenant_id,
            communities_detected=len(communities),
            summaries_generated=summaries_generated,
            duration_seconds=duration,
            incremental=False,
        )
        logger.info(
            "graphrag_full_index_complete",
            extra={
                "tenant_id": tenant_id,
                "communities": len(communities),
                "summaries": summaries_generated,
                "duration_seconds": round(duration, 3),
            },
        )
        return result

    async def index_incremental(
        self,
        entity_id: str,
        tenant_id: str,
    ) -> IndexingResult:
        """Run community detection on the 2-hop subgraph around *entity_id*.

        Only the communities that contain *entity_id* or its neighbors are
        re-summarised.
        """
        t0 = time.perf_counter()
        GRAPHRAG_UPDATE_FREQUENCY.labels(tenant_id=tenant_id).inc()

        communities = await self._detector.detect_communities_for_entity(
            entity_id, tenant_id, hop_depth=2
        )
        summaries_generated = await self._summarize_and_store(communities, tenant_id)

        duration = time.perf_counter() - t0
        GRAPHRAG_INDEX_LATENCY.labels(tenant_id=tenant_id, mode="incremental").observe(duration)

        result = IndexingResult(
            tenant_id=tenant_id,
            communities_detected=len(communities),
            summaries_generated=summaries_generated,
            duration_seconds=duration,
            incremental=True,
        )
        logger.debug(
            "graphrag_incremental_index_complete",
            extra={
                "entity_id": entity_id,
                "tenant_id": tenant_id,
                "communities": len(communities),
                "summaries": summaries_generated,
                "duration_seconds": round(duration, 3),
            },
        )
        return result

    async def get_community_summaries(self, tenant_id: str) -> list[dict[str, object]]:
        """Query Neo4j for all nodes with a ``community_summary`` property set.

        Returns a list of dicts, each containing ``community_id``,
        ``community_summary``, and ``entity_count`` for each distinct community
        found for *tenant_id*.
        """
        async with self._summarizer._driver.session() as session:
            result = await session.run(
                "MATCH (n:STIXEntity {tenant_id: $tenant_id}) "
                "WHERE n.community_summary IS NOT NULL "
                "RETURN n.community_id AS community_id, "
                "       n.community_summary AS community_summary, "
                "       count(n) AS entity_count "
                "ORDER BY n.community_id",
                tenant_id=tenant_id,
            )
            records = await result.data()
        return [
            {
                "community_id": r["community_id"],
                "community_summary": r["community_summary"],
                "entity_count": r["entity_count"],
            }
            for r in records
        ]

    async def schedule_background_index(
        self,
        tenant_id: str,
        *,
        interval_seconds: int = 300,
    ) -> None:
        """Start a background :mod:`asyncio` task for periodic full re-indexing.

        Calling this method a second time cancels any existing background task
        before starting a new one.
        """
        if self._background_task is not None and not self._background_task.done():
            self._background_task.cancel()
            try:
                await self._background_task
            except asyncio.CancelledError:
                pass

        async def _loop() -> None:
            while True:
                try:
                    await self.index_full(tenant_id)
                except Exception as exc:
                    logger.error(
                        "background_index_error",
                        extra={"tenant_id": tenant_id, "error": str(exc)},
                    )
                await asyncio.sleep(interval_seconds)

        self._background_task = asyncio.create_task(_loop())
        logger.info(
            "background_index_scheduled",
            extra={"tenant_id": tenant_id, "interval_seconds": interval_seconds},
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _summarize_and_store(
        self,
        communities: list[CommunityResult],
        tenant_id: str,
    ) -> int:
        """Generate and store summaries for *communities*.  Returns count stored."""
        stored = 0
        for community in communities:
            summary = await self._summarizer.summarize_community(community)
            await self._summarizer.store_summary_for_community(summary, community.entity_ids)
            GRAPHRAG_SUMMARIES_UPDATED.labels(tenant_id=tenant_id).inc()
            stored += 1
        return stored
