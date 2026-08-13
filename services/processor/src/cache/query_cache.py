"""3-tier query result cache for the /search endpoint.

Tier 1 — Exact match (SHA-256 hash in Redis).
Tier 2 — Fuzzy text match (RediSearch FT.SEARCH).
Tier 3 — Semantic match (Qdrant cosine similarity on query embeddings).

Fail-open design: if Redis or Qdrant is unavailable, all cache checks
return None (cache miss) so search continues without caching.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any

import redis.asyncio as aioredis
from prometheus_client import Counter
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams
from redis.exceptions import ConnectionError, ResponseError

logger = logging.getLogger(__name__)

# --- Prometheus metrics ------------------------------------------------------

_CACHE_HIT = Counter(
    "processor_cache_hit_total",
    "Search cache hits by tier",
    ["cache_tier"],
)

_CACHE_MISS = Counter(
    "processor_cache_miss_total",
    "Search cache misses (all tiers exhausted)",
)

# --- RediSearch index creation Lua -------------------------------------------
# We use FT.CREATE via Python rather than a Lua script because the schema is
# constant and FT.CREATE is idempotent with FT.INFO guard.

_REDISEARCH_SCHEMA = "ON HASH PREFIX 1 cache:rs: " "SCHEMA " "query_text TEXT " "tenant_id TAG " "search_id TAG " "created_at NUMERIC SORTABLE"

_QDRANT_COLLECTION = "query_embeddings"


class QueryCacheService:
    """3-tier search cache: exact → fuzzy → semantic.

    Each cached entry stores:
    - Tier-1 key:  ``cache:exact:{tenant_id}:{sha256hex}``  → search_id pointer
    - Result key:  ``cache:result:{tenant_id}:{search_id}``  → full JSON response
    - RediSearch:  ``cache:rs:{tenant_id}:{search_id}``      → indexed query_text
    - Qdrant:      point in ``query_embeddings`` collection   → embedding + payload

    Parameters
    ----------
    redis_url: Redis connection URL (redis://…).
    qdrant_url: Qdrant REST API URL (http://…).
    qdrant_api_key: Optional Qdrant API key.
    ttl_seconds: Cache TTL in seconds (default 3600 = 1 hour).
    embedding_dim: Embedding vector dimension (default 1024 for BGE-M3).
    """

    def __init__(
        self,
        redis_url: str,
        qdrant_url: str,
        qdrant_api_key: str | None = None,
        ttl_seconds: int = 3600,
        embedding_dim: int = 1024,
    ) -> None:
        self._redis_url = redis_url
        self._qdrant_url = qdrant_url
        self._qdrant_api_key = qdrant_api_key
        self._ttl = ttl_seconds
        self._embedding_dim = embedding_dim

        self._redis: aioredis.Redis | None = None
        self._qdrant: AsyncQdrantClient | None = None
        self._indices_ensured: bool = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Initialise Redis and Qdrant clients."""
        self._redis = aioredis.from_url(  # type: ignore[no-untyped-call]
            self._redis_url, decode_responses=True
        )
        self._qdrant = AsyncQdrantClient(url=self._qdrant_url, api_key=self._qdrant_api_key)
        # Best-effort index creation — failures are logged but don't break.
        await self.ensure_indices()

    async def close(self) -> None:
        """Close Redis and Qdrant connections."""
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None
        if self._qdrant is not None:
            await self._qdrant.close()
            self._qdrant = None

    # ------------------------------------------------------------------
    # Index setup
    # ------------------------------------------------------------------

    async def ensure_indices(self) -> None:
        """Create RediSearch index and Qdrant collection if they don't exist.

        Idempotent — safe to call multiple times.
        """
        if self._indices_ensured:
            return

        await self._ensure_redisearch_index()
        await self._ensure_qdrant_collection()
        self._indices_ensured = True

    async def _ensure_redisearch_index(self) -> None:
        if self._redis is None:
            return
        try:
            # FT.INFO returns an error if the index doesn't exist, so we guard
            await self._redis.execute_command("FT.INFO", "idx:query_cache")
            logger.debug("RediSearch index idx:query_cache already exists")
        except (ConnectionError, ResponseError):
            try:
                await self._redis.execute_command("FT.CREATE", "idx:query_cache", *_REDISEARCH_SCHEMA.split())
                logger.info("RediSearch index idx:query_cache created")
            except ResponseError as exc:
                # Race condition — another worker created it first
                if "already exists" in str(exc).lower():
                    logger.debug("RediSearch index already exists (concurrent creation)")
                else:
                    logger.warning("RediSearch FT.CREATE failed: %s", exc)
            except ConnectionError as exc:
                logger.warning("Redis unavailable during FT.CREATE: %s", exc)

    async def _ensure_qdrant_collection(self) -> None:
        if self._qdrant is None:
            return
        try:
            collections = await self._qdrant.get_collections()
            names = {c.name for c in collections.collections}
            if _QDRANT_COLLECTION in names:
                logger.debug("Qdrant collection %s already exists", _QDRANT_COLLECTION)
                return
        except Exception:
            logger.warning("Qdrant unavailable during collection check — cache will be fail-open")
            return
        try:
            await self._qdrant.create_collection(
                collection_name=_QDRANT_COLLECTION,
                vectors_config=VectorParams(size=self._embedding_dim, distance=Distance.COSINE),
            )
            logger.info("Qdrant collection %s created", _QDRANT_COLLECTION)
        except Exception as exc:
            if "already exists" in str(exc).lower():
                logger.debug("Qdrant collection already exists")
            else:
                logger.warning("Qdrant collection creation failed: %s", exc)

    # ------------------------------------------------------------------
    # Cache check — 3-tier lookup
    # ------------------------------------------------------------------

    async def check_cache(self, tenant_id: str, query: str) -> dict[str, Any] | None:
        """Check all three cache tiers for a matching cached result.

        Returns ``None`` on cache miss (fail-open when infrastructure is down).

        Returns
        -------
        dict | None
            If found, returns ``{"cached": True, "cache_tier": "exact"|"fuzzy"|"semantic",
            ...cached_response_fields}``.
        """
        # Tier 1 — Exact match via SHA-256 hash
        result = await self._check_exact(tenant_id, query)
        if result is not None:
            _CACHE_HIT.labels(cache_tier="exact").inc()
            logger.debug("Cache hit (exact)", extra={"tenant_id": tenant_id})
            return result

        # Tier 2 — Fuzzy text match via RediSearch
        result = await self._check_fuzzy(tenant_id, query)
        if result is not None:
            _CACHE_HIT.labels(cache_tier="fuzzy").inc()
            logger.debug("Cache hit (fuzzy)", extra={"tenant_id": tenant_id})
            return result

        # Tier 3 — Semantic match via Qdrant
        result = await self._check_semantic(tenant_id, query)
        if result is not None:
            _CACHE_HIT.labels(cache_tier="semantic").inc()
            logger.debug("Cache hit (semantic)", extra={"tenant_id": tenant_id})
            return result

        _CACHE_MISS.inc()
        logger.debug("Cache miss", extra={"tenant_id": tenant_id})
        return None

    # ------------------------------------------------------------------
    # Tier 1 — Exact match
    # ------------------------------------------------------------------

    async def _check_exact(self, tenant_id: str, query: str) -> dict[str, Any] | None:
        """SHA-256 hash lookup in Redis."""
        query_norm = self._normalize_query(query)
        hash_key = hashlib.sha256(f"{tenant_id}:{query_norm}".encode()).hexdigest()
        exact_key = f"cache:exact:{tenant_id}:{hash_key}"
        try:
            search_id = await self._redis_get(exact_key)
            if search_id is None:
                return None
            result = await self._load_result(tenant_id, search_id)
            if result is None:
                return None
            result["cached"] = True
            result["cache_tier"] = "exact"
            return result
        except (ConnectionError, ResponseError) as exc:
            logger.warning("Redis error in exact cache check: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Tier 2 — Fuzzy text match via RediSearch
    # ------------------------------------------------------------------

    async def _check_fuzzy(self, tenant_id: str, query: str) -> dict[str, Any] | None:
        """Search RediSearch for fuzzy-matched query text."""
        if self._redis is None:
            return None
        # Check if RediSearch module is available
        if not await self._has_redisearch():
            return None
        try:
            escaped = self._escape_redisearch_query(query)
            ft_client = self._redis.ft("idx:query_cache")  # type: ignore[no-untyped-call]
            # Use RediSearch prefix matching: query_text starts with the escaped
            # query string.  The `%` wrapping was invalid RediSearch syntax and
            # caused "Syntax error at offset N near ..." on every fuzzy check.
            result: Any = await ft_client.search(
                f"@query_text:{escaped}* @tenant_id:{{{tenant_id}}}",
            )
            if not result or not result.docs:
                return None

            # Find best-scoring result above threshold
            threshold = 0.85
            best_doc = None
            best_score = 0.0
            for doc in result.docs:
                # RediSearch score as fraction of query length
                doc_score = float(getattr(doc, "score", 0.0)) / max(len(query), 1)
                if doc_score > best_score and doc_score > threshold:
                    best_score = doc_score
                    best_doc = doc

            if best_doc is None:
                return None

            search_id = best_doc.search_id
            cached_result = await self._load_result(tenant_id, search_id)
            if cached_result is None:
                return None
            cached_result["cached"] = True
            cached_result["cache_tier"] = "fuzzy"
            return cached_result
        except (ConnectionError, ResponseError) as exc:
            logger.warning("RediSearch error in fuzzy cache check: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Tier 3 — Semantic match via Qdrant
    # ------------------------------------------------------------------

    async def _check_semantic(self, tenant_id: str, query: str) -> dict[str, Any] | None:
        """Embed query and search Qdrant for nearest neighbour."""
        if self._qdrant is None:
            return None
        try:
            embedding = await self._embed_query(query)
            if embedding is None:
                return None
        except Exception as exc:
            logger.warning("Embedding failed in semantic cache check: %s", exc)
            return None

        try:
            results = await self._qdrant.search(
                collection_name=_QDRANT_COLLECTION,
                query_vector=embedding,
                limit=1,
                score_threshold=0.92,
                query_filter={"must": [{"key": "tenant_id", "match": {"value": tenant_id}}]},
            )
            if not results:
                return None

            # Qdrant returns cosine similarity — check threshold
            top = results[0]
            if top.score < 0.92:
                return None

            search_id = top.payload.get("search_id")  # type: ignore[union-attr]
            if not search_id:
                return None

            cached_result = await self._load_result(tenant_id, search_id)
            if cached_result is None:
                return None
            cached_result["cached"] = True
            cached_result["cache_tier"] = "semantic"
            return cached_result
        except Exception as exc:
            logger.warning("Qdrant error in semantic cache check: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Cache store
    # ------------------------------------------------------------------

    async def store_cache(
        self,
        tenant_id: str,
        search_id: str,
        query: str,
        response: dict[str, Any],
    ) -> None:
        """Store the search result across all three cache tiers.

        Fail-open: errors are logged but never raised.
        """
        now = time.time()

        # Add metadata to the cached response
        cached = {
            **response,
            "cached": True,
            "cache_tier": "stored",
            "entity_count": len(response.get("entities", [])),
        }

        # ── Tier 1: exact match pointer + result ──
        query_norm = self._normalize_query(query)
        hash_key = hashlib.sha256(f"{tenant_id}:{query_norm}".encode()).hexdigest()
        exact_key = f"cache:exact:{tenant_id}:{hash_key}"
        result_key = f"cache:result:{tenant_id}:{search_id}"

        try:
            if self._redis is not None:
                await self._redis.setex(result_key, self._ttl, json.dumps(cached))
                await self._redis.setex(exact_key, self._ttl, search_id)
        except (ConnectionError, ResponseError) as exc:
            logger.warning("Redis error in store_cache (Tier 1): %s", exc)

        # ── Tier 2: RediSearch document ──
        try:
            if self._redis is not None and await self._has_redisearch():
                rs_key = f"cache:rs:{tenant_id}:{search_id}"
                await self._redis.hset(  # type: ignore[no-untyped-call]
                    rs_key,
                    mapping={
                        "query_text": query,
                        "tenant_id": tenant_id,
                        "search_id": search_id,
                        "created_at": str(now),
                    },
                )
                await self._redis.expire(rs_key, self._ttl)
        except (ConnectionError, ResponseError) as exc:
            logger.warning("RediSearch error in store_cache (Tier 2): %s", exc)

        # ── Tier 3: Qdrant point ──
        try:
            if self._qdrant is not None:
                embedding = await self._embed_query(query)
                if embedding is not None:
                    # Use query-content hash as point ID so repeated queries
                    # for the same text overwrite the same point (idempotent
                    # upsert) instead of creating duplicate embeddings.
                    query_norm = self._normalize_query(query)
                    point_id = int(hashlib.sha256(f"{tenant_id}:{query_norm}".encode()).hexdigest()[:15], 16)
                    await self._ensure_qdrant_collection()
                    await self._qdrant.upsert(
                        collection_name=_QDRANT_COLLECTION,
                        points=[
                            PointStruct(
                                id=point_id,
                                vector=embedding,
                                payload={
                                    "query_text": query,
                                    "search_id": search_id,
                                    "tenant_id": tenant_id,
                                    "created_at": now,
                                },
                            )
                        ],
                    )
        except Exception as exc:
            logger.warning("Qdrant error in store_cache (Tier 3): %s", exc)

        logger.debug(
            "Cache stored",
            extra={"tenant_id": tenant_id, "search_id": search_id, "ttl": self._ttl},
        )

    # ------------------------------------------------------------------
    # Cache invalidation
    # ------------------------------------------------------------------

    async def invalidate(self, tenant_id: str, search_id: str | None = None) -> None:
        """Remove cache entries for a tenant (optionally scoped to one search_id).

        When *search_id* is ``None``, all cached results for *tenant_id* are
        removed by scanning for matching keys.
        """
        if self._redis is None:
            return

        try:
            if search_id is not None:
                # Delete exact-match pointer and result
                result_key = f"cache:result:{tenant_id}:{search_id}"
                await self._redis.delete(result_key)
                # Also delete the RediSearch hash doc
                rs_key = f"cache:rs:{tenant_id}:{search_id}"
                await self._redis.delete(rs_key)
            else:
                # Scan and delete all keys for this tenant
                cursor: int = 0
                while True:
                    cursor, keys = await self._redis.scan(cursor, match=f"cache:*:{tenant_id}:*", count=100)
                    if keys:
                        await self._redis.delete(*keys)
                    if cursor == 0:
                        break

            # Qdrant: delete by payload filter
            if self._qdrant is not None:
                try:
                    must_conditions: list[dict[str, Any]] = [{"key": "tenant_id", "match": {"value": tenant_id}}]
                    if search_id is not None:
                        must_conditions.append({"key": "search_id", "match": {"value": search_id}})
                    await self._qdrant.delete(
                        collection_name=_QDRANT_COLLECTION,
                        points_selector={"filter": {"must": must_conditions}},
                    )
                except Exception as exc:
                    logger.warning("Qdrant delete in invalidate failed: %s", exc)
        except (ConnectionError, ResponseError) as exc:
            logger.warning("Invalidate error: %s", exc)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_query(query: str) -> str:
        """Normalize query for consistent hashing: lowercase + strip whitespace."""
        return query.lower().strip()

    @staticmethod
    def _escape_redisearch_query(query: str) -> str:
        """Escape special RediSearch characters in *query*.

        Characters escaped: ``, . < > { } [ ] " ' : ; ! @ # $ % ^ & * ( ) - + = ~``
        """
        special_chars = set(",.<>{}[]\"':;!@#$%^&*()-+=~")
        escaped: list[str] = []
        for ch in query:
            if ch in special_chars:
                escaped.append(f"\\{ch}")
            else:
                escaped.append(ch)
        return "".join(escaped)

    async def _has_redisearch(self) -> bool:
        """Check whether the connected Redis instance has the RediSearch module."""
        if self._redis is None:
            return False
        try:
            modules: list[Any] = await self._redis.module_list()
            module_names = [str(m.get("name", "")).lower() for m in modules]
            return any("search" in name for name in module_names)
        except (ConnectionError, ResponseError):
            return False

    async def _redis_get(self, key: str) -> str | None:
        """Safe Redis GET — returns None on any error."""
        if self._redis is None:
            return None
        try:
            return await self._redis.get(key)
        except (ConnectionError, ResponseError):
            return None

    async def _load_result(self, tenant_id: str, search_id: str) -> dict[str, Any] | None:
        """Load the full cached result JSON from Redis."""
        if self._redis is None:
            return None
        try:
            raw = await self._redis.get(f"cache:result:{tenant_id}:{search_id}")
            if raw is None:
                return None
            return json.loads(str(raw))
        except (ConnectionError, ResponseError, json.JSONDecodeError) as exc:
            logger.warning("Failed to load cached result: %s", exc)
            return None

    async def _embed_query(self, query: str) -> list[float] | None:
        """Generate embedding vector for *query* via the LLM client.

        Returns None on failure (fail-open).
        """
        try:
            from ..llm.client import LLMClient

            client = LLMClient()
            return await client.embed(query)
        except Exception as exc:
            logger.warning("Failed to embed query for cache: %s", exc)
            return None
