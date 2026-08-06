"""Temporal retrieval — coarse-to-fine hierarchy search via Postgres + Neo4j.

Search order: episode → window → turn → local_span (most recent fallback).
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from .profiler import QueryProfile
from .scored_context import ScoredContext

if TYPE_CHECKING:
    from ..graph.temporal_store import TemporalStore

logger = logging.getLogger(__name__)


def _cue_to_episode_ids(cues: list[str], tenant_id: str) -> list[str]:
    """Map spaCy temporal cue strings to deterministic episode ID candidates."""
    import dateparser  # soft dep — falls back gracefully if unavailable

    episode_ids: list[str] = []
    for cue in cues:
        try:
            parsed = dateparser.parse(cue, settings={"RETURN_AS_TIMEZONE_AWARE": True})
        except Exception:
            parsed = None
        if parsed is None:
            # Try treating the cue as an approximate "now" offset
            parsed = datetime.now(UTC)
        ts = int(parsed.timestamp())
        # Match the same hash strategy used during ingest (_assign_temporal_ids)
        eid = hashlib.sha256(f"{tenant_id}:unknown:{ts // 3600}".encode()).hexdigest()[:12]
        if eid not in episode_ids:
            episode_ids.append(eid)
    return episode_ids


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
        # Skip recency fallback for pure entity queries — avoid polluting relational fusion
        if not profile.temporal_cues and profile.route == "relational":
            return []

        # D1: resolve temporal cues to episode IDs and query hierarchy first
        candidate_ids: list[str] = []
        if profile.temporal_cues:
            episode_ids = _cue_to_episode_ids(profile.temporal_cues, tenant_id)
            for eid in episode_ids:
                ids = await self._store.query_episode_neighbors(eid, tenant_id, limit=top_k)
                for cid in ids:
                    if cid not in candidate_ids:
                        candidate_ids.append(cid)

        # D2: fall back to recency only when cue lookup found nothing
        if not candidate_ids:
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
