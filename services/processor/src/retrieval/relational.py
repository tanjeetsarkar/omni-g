"""Relational retrieval via entity alignment + APOC Personalized PageRank.

Algorithm (per V3 architecture):
  1. Embed anchor texts from QueryProfile → Qdrant cosine search → anchor Entity IDs
  2. Extract k-hop subgraph around anchor entities via CO_OCCURRED_IN edges
  3. Run APOC PPR (γ=0.6) on subgraph to score ContextUnit nodes
  4. Graceful fallback to Python BFS if APOC is unavailable
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import TYPE_CHECKING, Any

import redis.asyncio as aioredis
from prometheus_client import Counter

from ..llm.client import LLMClient
from .profiler import QueryProfile
from .scored_context import ScoredContext

if TYPE_CHECKING:
    from ..indexers.vector import ContextUnitIndexer

logger = logging.getLogger(__name__)

# Module-level config for query embedding (aligned with Entities collection dim=768)
EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")
OLLAMA_URL: str = os.getenv("OLLAMA_URL", "http://localhost:11434")
EMBEDDING_DIM: int = int(os.getenv("EMBEDDING_DIM", "768"))

# PPR cache config
PPR_CACHE_TTL: int = int(os.getenv("PPR_CACHE_TTL", "60"))
REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379")

# Prometheus counters for PPR cache
PPR_CACHE_HITS = Counter(
    "processor_ppr_cache_hits_total",
    "APOC PPR results served from Redis cache",
)

PPR_CACHE_MISSES = Counter(
    "processor_ppr_cache_misses_total",
    "APOC PPR results computed from scratch (cache miss)",
)


def _deterministic_hash_embed(text: str, dim: int = EMBEDDING_DIM) -> list[float]:
    """Generate a deterministic hash-based float vector for *text*.

    Each byte of successive SHA-256 blocks is mapped linearly to
    the range ``[-1.0, 1.0]`` to fill a vector of length *dim*.
    """
    seed = hashlib.sha256(text.encode()).digest()
    floats: list[float] = []
    block_idx = 0
    while len(floats) < dim:
        block = hashlib.sha256(seed + block_idx.to_bytes(4, "big")).digest()
        for byte in block:
            floats.append((byte - 127.5) / 127.5)
            if len(floats) >= dim:
                break
        block_idx += 1
    return floats[:dim]


async def _embed_query(text: str, dim: int = EMBEDDING_DIM) -> list[float]:
    """Generate semantic embedding using the configured LLM provider.

    Uses the unified :class:`LLMClient` (OpenRouter or Ollama). Falls back on
    deterministic hash-based generator if the LLM is unreachable.
    """
    try:
        vector = await LLMClient().embed(text)
        if isinstance(vector, list):
            if len(vector) < dim:
                return vector + [0.0] * (dim - len(vector))
            return vector[:dim]
        logger.warning("invalid_embedding_response_structure", extra={"response": vector})
    except Exception as exc:
        logger.warning(
            "embedding_failed_using_fallback_hash",
            extra={"error": str(exc)},
        )

    return _deterministic_hash_embed(text, dim)


async def _get_redis_client() -> aioredis.Redis | None:
    """Return a shared Redis client, or ``None`` if Redis is unreachable."""
    try:
        client: aioredis.Redis = aioredis.from_url(REDIS_URL, decode_responses=True)
        await client.ping()
        return client
    except Exception as exc:
        logger.warning(
            "ppr_cache_redis_unavailable",
            extra={"error": str(exc), "redis_url": REDIS_URL},
        )
        return None


def _cache_key_anchor_hash(anchor_ids: list[str]) -> str:
    """Return a deterministic short hash of a sorted list of anchor entity IDs.

    Used to build a PPR cache key that is stable for the same set of anchors
    regardless of their order in the list.
    """
    sorted_ids = sorted(anchor_ids)
    return hashlib.sha256("|".join(sorted_ids).encode()).hexdigest()[:16]


class RelationalRetriever:
    """Retrieves ContextUnits via entity-centric multi-hop graph traversal."""

    def __init__(
        self,
        neo4j_driver: Any,
        qdrant_client: Any,
        vector_indexer: ContextUnitIndexer,
    ) -> None:
        self._driver = neo4j_driver
        self._qdrant = qdrant_client
        self._indexer = vector_indexer

    async def retrieve(
        self,
        profile: QueryProfile,
        tenant_id: str,
        d_max: int = 3,
        top_k: int = 20,
    ) -> list[ScoredContext]:
        """Return top-*top_k* ContextUnits relevant to *profile* for *tenant_id*."""
        anchor_ids = await self._align_entities(profile, tenant_id, top_k=10)
        if not anchor_ids:
            logger.debug("relational_no_anchors", extra={"tenant_id": tenant_id})
            return []

        try:
            results = await self._ppr_retrieve(anchor_ids, tenant_id, d_max, top_k)
            if results:
                return results
            # APOC returned nothing — fall through to BFS
        except Exception as exc:
            logger.warning(
                "apoc_ppr_failed_falling_back_to_bfs",
                extra={"error": str(exc), "tenant_id": tenant_id},
            )

        return await self._bfs_retrieve(anchor_ids, tenant_id, top_k)

    # ------------------------------------------------------------------
    # Step 1: Entity alignment via Qdrant cosine
    # ------------------------------------------------------------------

    async def _align_entities(self, profile: QueryProfile, tenant_id: str, top_k: int = 10) -> list[str]:
        """Find anchor Entity IDs via cosine similarity in the entities Qdrant collection."""
        anchor_texts = profile.anchor_texts or [profile.query]
        collection_name = f"entities_{tenant_id}"
        try:
            try:
                exists = await self._qdrant.collection_exists(collection_name)
            except Exception:
                logger.warning(
                    "qdrant_collection_exists_failed",
                    extra={"collection": collection_name, "tenant_id": tenant_id},
                )
                exists = False

            if not exists:
                logger.debug(
                    "entities_fallback_collection_missing",
                    extra={"collection": collection_name, "tenant_id": tenant_id},
                )
                return []

            vector = await _embed_query(anchor_texts[0])
            hits = await self._qdrant.search(
                collection_name=collection_name,
                query_vector=vector,
                limit=top_k,
            )
            return [str(h.payload["entity_id"]) for h in hits if h.payload and h.payload.get("entity_id")]
        except Exception:
            logger.exception("entity_alignment_failed", extra={"tenant_id": tenant_id})
            return []

    # ------------------------------------------------------------------
    # Step 3: APOC PPR (preferred path)
    # ------------------------------------------------------------------

    async def _ppr_retrieve(
        self,
        anchor_ids: list[str],
        tenant_id: str,
        d_max: int,
        top_k: int,
    ) -> list[ScoredContext]:
        """Localised PPR via APOC: k-hop subgraph around anchors → PageRank.

        Results are cached in Redis with a short TTL (default 60 s) keyed on
        ``ppr:{tenant_id}:{hash(sorted(anchor_ids))}:{d_max}`` so that repeated
        queries for the same anchor set within the cache window avoid redundant
        APOC computation.
        """
        # ── Check Redis cache first ────────────────────────────────────────
        cache_key = f"ppr:{tenant_id}:{_cache_key_anchor_hash(anchor_ids)}:{d_max}"
        redis_client = await _get_redis_client()
        if redis_client is not None:
            try:
                cached = await redis_client.get(cache_key)
                if cached is not None:
                    PPR_CACHE_HITS.inc()
                    logger.debug(
                        "ppr_cache_hit",
                        extra={"cache_key": cache_key, "tenant_id": tenant_id},
                    )
                    cached_data = json.loads(cached)
                    await redis_client.aclose()
                    return [
                        ScoredContext(
                            context_id=item["context_id"],
                            score=float(item["score"]),
                            text=item.get("text") or "",
                        )
                        for item in cached_data
                    ]
            except Exception as exc:
                logger.warning(
                    "ppr_cache_read_failed_proceeding_with_computation",
                    extra={"error": str(exc), "cache_key": cache_key},
                )

        PPR_CACHE_MISSES.inc()
        logger.debug(
            "ppr_cache_miss",
            extra={"cache_key": cache_key, "tenant_id": tenant_id},
        )

        # ── Compute PPR via networkx (replaces removed APOC procedure) ────
        # apoc.algo.pageRankWithConfig was deleted in APOC 5.x; we now fetch
        # the k-hop subgraph via apoc.path.subgraphNodes (still supported) and
        # run Personalized PageRank in Python via networkx. See
        # src.retrieval.pagerank.pagerank_subgraph for the shared helper.
        from .pagerank import pagerank_subgraph

        async with self._driver.session() as session:
            rows = await pagerank_subgraph(
                session,
                anchor_ids=anchor_ids,
                tenant_id=tenant_id,
                d_max=d_max,
                gamma=0.6,
                top_k=top_k,
            )

        results = rows

        # ── Store in Redis cache ───────────────────────────────────────────
        if redis_client is not None and results:
            try:
                serialised = json.dumps(
                    [
                        {
                            "context_id": r.context_id,
                            "score": r.score,
                            "text": r.text,
                        }
                        for r in results
                    ],
                    default=str,
                )
                await redis_client.setex(cache_key, PPR_CACHE_TTL, serialised)
                logger.debug(
                    "ppr_cache_stored",
                    extra={
                        "cache_key": cache_key,
                        "ttl": PPR_CACHE_TTL,
                        "result_count": len(results),
                    },
                )
            except Exception as exc:
                logger.warning(
                    "ppr_cache_write_failed",
                    extra={"error": str(exc), "cache_key": cache_key},
                )
            finally:
                await redis_client.aclose()

        return results

    # ------------------------------------------------------------------
    # Step 3 fallback: Python BFS via Cypher
    # ------------------------------------------------------------------

    async def _bfs_retrieve(
        self,
        anchor_ids: list[str],
        tenant_id: str,
        top_k: int,
    ) -> list[ScoredContext]:
        """BFS fallback: traverse CO_OCCURRED_IN edges 1 hop from anchor entities."""
        cypher = """
        MATCH (anchor:Entity)-[:CO_OCCURRED_IN]->(ctx:ContextUnit)
        WHERE anchor.id IN $anchor_ids AND ctx.tenant_id = $tenant_id

        OPTIONAL MATCH (ctx)<-[:CO_OCCURRED_IN]-(related:Entity)
        WHERE related.tenant_id = $tenant_id

        WITH ctx, count(DISTINCT related) AS entity_count
        RETURN ctx.id AS context_id, ctx.text AS text,
               toFloat(entity_count) / 10.0 AS score,
               [] AS entity_ids
        ORDER BY score DESC LIMIT $top_k
        """
        try:
            async with self._driver.session() as session:
                result = await session.run(
                    cypher,
                    anchor_ids=anchor_ids,
                    tenant_id=tenant_id,
                    top_k=top_k,
                )
                rows = await result.data()
        except Exception:
            logger.exception("bfs_retrieve_failed", extra={"tenant_id": tenant_id})
            return []

        return [
            ScoredContext(
                context_id=row["context_id"],
                score=max(float(row.get("score", 0.0)), 0.01),
                text=row.get("text") or "",
                entity_ids=row.get("entity_ids") or [],
            )
            for row in rows
        ]
