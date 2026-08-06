"""Temporal retrieval — coarse-to-fine hierarchy search via Postgres + Neo4j.

Search order: episode → window → turn → local_span (most recent fallback).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .profiler import QueryProfile
from .scored_context import ScoredContext

if TYPE_CHECKING:
    from ..graph.temporal_store import TemporalStore

logger = logging.getLogger(__name__)


class TemporalRetriever:
    """Retrieves ContextUnits ordered by recency using the temporal hierarchy."""

    def __init__(self, temporal_store: TemporalStore, neo4j_driver: Any) -> None:
        self._store = temporal_store
        self._driver = neo4j_driver

    async def retrieve(
        self,
        profile: QueryProfile,
        tenant_id: str,
        top_k: int = 20,
    ) -> list[ScoredContext]:
        """Return *top_k* ContextUnits from the temporal hierarchy for *tenant_id*."""
        # Try episode/window/turn IDs extracted from temporal cues (future work: parse cues)
        # Fall back to recency ordering from Neo4j
        candidate_ids = await self._store.query_recent(tenant_id, limit=top_k * 2)

        if not candidate_ids:
            return await self._neo4j_recent(tenant_id, top_k)

        contexts = await self._fetch_contexts_by_ids(candidate_ids, tenant_id)
        # Score by recency: earlier in the list = more recent = higher score
        result = []
        for i, ctx in enumerate(contexts):
            score = 1.0 - (i / max(len(contexts), 1))
            result.append(
                ScoredContext(
                    context_id=ctx["context_id"],
                    score=score,
                    text=ctx.get("text") or "",
                    entity_ids=ctx.get("entity_ids") or [],
                )
            )
        return result[:top_k]

    async def _fetch_contexts_by_ids(self, ids: list[str], tenant_id: str) -> list[dict[str, Any]]:
        try:
            async with self._driver.session() as session:
                result = await session.run(
                    """
                    MATCH (ctx:ContextUnit)
                    WHERE ctx.id IN $ids AND ctx.tenant_id = $tenant_id
                    OPTIONAL MATCH (entity:Entity)-[:CO_OCCURRED_IN]->(ctx)
                    RETURN ctx.id AS context_id, ctx.text AS text,
                           collect(DISTINCT entity.id) AS entity_ids
                    """,
                    ids=ids,
                    tenant_id=tenant_id,
                )
                return await result.data()
        except Exception:
            logger.exception("fetch_contexts_by_ids_failed")
            return []

    async def _neo4j_recent(self, tenant_id: str, top_k: int) -> list[ScoredContext]:
        """Direct Neo4j fallback when temporal store returns nothing."""
        try:
            async with self._driver.session() as session:
                result = await session.run(
                    """
                    MATCH (ctx:ContextUnit)
                    WHERE ctx.tenant_id = $tenant_id
                    OPTIONAL MATCH (entity:Entity)-[:CO_OCCURRED_IN]->(ctx)
                    RETURN ctx.id AS context_id, ctx.text AS text,
                           collect(DISTINCT entity.id) AS entity_ids,
                           ctx.created AS created
                    ORDER BY created DESC LIMIT $top_k
                    """,
                    tenant_id=tenant_id,
                    top_k=top_k,
                )
                rows = await result.data()
        except Exception:
            logger.exception("neo4j_recent_failed", extra={"tenant_id": tenant_id})
            return []

        return [
            ScoredContext(
                context_id=row["context_id"],
                score=0.5,
                text=row.get("text") or "",
                entity_ids=row.get("entity_ids") or [],
            )
            for row in rows
        ]
