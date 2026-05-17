from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any

import redis.asyncio as aioredis
from redis.exceptions import ConnectionError, ResponseError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lua script: atomic check-and-set with sliding-window TTL
# ---------------------------------------------------------------------------
# KEYS[1] = dedup key  (e.g. "dedup:{tenant_id}:{sha256hex}")
# ARGV[1] = TTL in seconds
#
# Returns "duplicate" if the key already existed (TTL is refreshed).
# Returns "new"       if the key was freshly created.
# ---------------------------------------------------------------------------
_LUA_SCRIPT = """\
local key = KEYS[1]
local ttl = tonumber(ARGV[1])
local exists = redis.call('EXISTS', key)
if exists == 1 then
    redis.call('EXPIRE', key, ttl)
    return 'duplicate'
else
    redis.call('SET', key, '1', 'EX', ttl)
    return 'new'
end"""


@dataclass
class DedupResult:
    """Result of a single deduplication check."""

    is_duplicate: bool
    content_hash: str
    event_id: str | None = None


class ContentDeduplicator:
    """SHA-256 content deduplication backed by Redis with sliding-window TTL.

    Fail-open design: when Redis is unavailable every event is treated as
    non-duplicate so that ingestion is never blocked.
    """

    def __init__(self, ttl_seconds: int = 86400) -> None:
        self._ttl_seconds = ttl_seconds
        self._client: aioredis.Redis | None = None
        self._script_sha: str | None = None
        self._has_redisearch: bool = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self, url: str) -> None:
        """Open the Redis connection, register the Lua script, and detect RediSearch."""
        client: aioredis.Redis = aioredis.from_url(url, decode_responses=True)  # type: ignore[no-untyped-call]
        self._client = client
        try:
            try:
                self._script_sha = await client.script_load(_LUA_SCRIPT)
            except ResponseError as exc:
                logger.warning(
                    "Lua scripting unavailable (%s) — will use non-atomic fallback", exc
                )
            modules: list[Any] = await client.module_list()
            module_names = [str(m.get("name", "")).lower() for m in modules]
            self._has_redisearch = any("search" in name for name in module_names)
            if self._has_redisearch:
                await self._ensure_search_index()
        except ConnectionError as exc:
            logger.warning(
                "Redis unavailable during connect — deduplication degraded: %s",
                exc,
                extra={"metric": "dedup_redis_unavailable", "value": 1},
            )

    async def close(self) -> None:
        """Close the Redis connection."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # Core deduplication
    # ------------------------------------------------------------------

    async def check_and_set(self, tenant_id: str, event: dict[str, Any]) -> DedupResult:
        """Atomically check whether *event* has been seen and mark it if not.

        Key format: ``dedup:{tenant_id}:{sha256hex}``

        Fail-open: returns ``is_duplicate=False`` when Redis is unreachable so
        that the ingestion pipeline is never blocked by deduplication failures.
        """
        content_hash = _hash_event(event)
        raw_event_id = event.get("event_id")
        event_id: str | None = str(raw_event_id) if raw_event_id is not None else None

        if self._client is None:
            logger.warning(
                "Redis client not initialised — treating event as non-duplicate (fail-open)",
                extra={"metric": "dedup_redis_unavailable", "value": 1},
            )
            return DedupResult(is_duplicate=False, content_hash=content_hash, event_id=event_id)

        key = f"dedup:{tenant_id}:{content_hash}"
        try:
            lua_result = await self._call_lua(key)
            is_dup = lua_result == "duplicate"
            logger.debug(
                "Dedup check: %s key=%s",
                lua_result,
                key,
                extra={
                    "metric": "dedup_hits" if is_dup else "dedup_misses",
                    "value": 1,
                    "tenant_id": tenant_id,
                },
            )
            return DedupResult(is_duplicate=is_dup, content_hash=content_hash, event_id=event_id)
        except ConnectionError as exc:
            logger.warning(
                "Redis connection error in check_and_set — failing open: %s",
                exc,
                extra={"metric": "dedup_redis_unavailable", "value": 1},
            )
            return DedupResult(is_duplicate=False, content_hash=content_hash, event_id=event_id)

    # ------------------------------------------------------------------
    # Botnet / source clustering via RediSearch
    # ------------------------------------------------------------------

    async def find_similar(self, tenant_id: str, source: str) -> list[str]:
        """Return dedup key IDs for a given *tenant_id* and *source* via FT.SEARCH.

        Enables botnet-dedup clustering: discover coordinated re-posts from the
        same source within the dedup window.

        Returns an empty list when RediSearch is unavailable or Redis is not
        connected.
        """
        if self._client is None or not self._has_redisearch:
            logger.warning(
                "RediSearch unavailable — find_similar returning empty list",
                extra={"metric": "dedup_search_unavailable", "value": 1},
            )
            return []
        try:
            ft_client = self._client.ft("dedup_idx")  # type: ignore[no-untyped-call]
            result: Any = await ft_client.search(
                f"@tenant_id:{{{tenant_id}}} @source:{source}"
            )
            return [str(doc.id) for doc in result.docs]
        except (ConnectionError, ResponseError) as exc:
            logger.warning("RediSearch FT.SEARCH failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _call_lua(self, key: str) -> str:
        """Execute the dedup Lua script via EVALSHA, falling back to EVAL, then to a
        non-atomic Python implementation when Lua is unavailable (e.g. in tests)."""
        assert self._client is not None  # guarded by caller  # noqa: S101
        if self._script_sha is not None:
            try:
                raw_evalsha = await self._client.evalsha(  # type: ignore[misc]
                    self._script_sha, 1, key, str(self._ttl_seconds)
                )
                return str(raw_evalsha)
            except ResponseError as exc:
                if "noscript" in str(exc).lower() or "unknown" in str(exc).lower():
                    # Script was flushed or Lua not available — fall through
                    logger.warning("EVALSHA failed (%s) — falling back", exc)
                    self._script_sha = None
                else:
                    raise
        try:
            raw_eval = await self._client.eval(  # type: ignore[misc]
                _LUA_SCRIPT, 1, key, str(self._ttl_seconds)
            )
            result = str(raw_eval)
            # Re-register so future calls use the faster EVALSHA path
            try:
                self._script_sha = await self._client.script_load(_LUA_SCRIPT)
            except (ConnectionError, ResponseError):
                pass
            return result
        except ResponseError as exc:
            if "unknown" in str(exc).lower():
                # Lua scripting not available in this Redis (e.g. fakeredis without lua extra)
                logger.warning(
                    "Lua scripting unavailable (%s) — using non-atomic Python fallback", exc
                )
                return await self._check_and_set_noatom(key)
            raise

    async def _check_and_set_noatom(self, key: str) -> str:
        """Non-atomic EXISTS+SET fallback used when Lua scripting is unavailable.

        Note: this path has a TOCTOU race condition and should only be used in
        environments that do not support EVAL (e.g. test fixtures with fakeredis).
        Production deployments always use the atomic Lua path.
        """
        assert self._client is not None  # noqa: S101
        exists = await self._client.exists(key)
        if exists:
            await self._client.expire(key, self._ttl_seconds)
            return "duplicate"
        await self._client.set(key, "1", ex=self._ttl_seconds)
        return "new"

    async def _ensure_search_index(self) -> None:
        """Create the ``dedup_idx`` RediSearch index if it does not already exist."""
        if self._client is None:
            return
        try:
            from redis.commands.search.field import TagField, TextField
            from redis.commands.search.indexDefinition import IndexDefinition, IndexType

            definition = IndexDefinition(prefix=["dedup:"], index_type=IndexType.HASH)  # type: ignore[no-untyped-call]
            ft_client = self._client.ft("dedup_idx")  # type: ignore[no-untyped-call]
            await ft_client.create_index(
                [TextField("source", no_stem=True), TagField("tenant_id")],
                definition=definition,
            )
            logger.info("RediSearch index 'dedup_idx' created")
        except ResponseError as exc:
            if "already exists" in str(exc).lower():
                logger.debug("RediSearch index 'dedup_idx' already exists — skipping creation")
            else:
                logger.warning("Failed to create RediSearch index: %s", exc)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _hash_event(event: dict[str, Any]) -> str:
    """Return the SHA-256 hex digest of the canonical sorted-key JSON of *event*."""
    canonical = json.dumps(event, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
