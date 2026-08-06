"""Postgres-backed temporal hierarchy store for ContextUnit ordering.

Provides coarse-to-fine time-window queries used by the TemporalRetriever:
  episode → window → turn → local_span
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    import asyncpg  # noqa

    from ..models.entities import ContextUnit


class TemporalStore:
    """Asyncpg-backed store for ContextUnit temporal hierarchy metadata."""

    def __init__(self, postgres_url: str) -> None:
        self._url = postgres_url
        self._pool: Any = None  # asyncpg.Pool once connected

    async def connect(self) -> None:
        """Create the connection pool and initialise the schema."""
        import asyncpg

        self._pool = await asyncpg.create_pool(self._url, min_size=1, max_size=5)
        await self._ensure_schema()
        logger.info("TemporalStore connected", extra={"postgres_url": self._url})

    async def _ensure_schema(self) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS context_units_temporal (
                    id          TEXT        PRIMARY KEY,
                    tenant_id   TEXT        NOT NULL,
                    session_id  TEXT,
                    episode_id  TEXT,
                    window_id   TEXT,
                    turn_id     TEXT,
                    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );

                CREATE INDEX IF NOT EXISTS idx_temporal_tenant_episode
                    ON context_units_temporal(tenant_id, episode_id, created_at);

                CREATE INDEX IF NOT EXISTS idx_temporal_tenant_window
                    ON context_units_temporal(tenant_id, window_id, created_at);

                CREATE INDEX IF NOT EXISTS idx_temporal_tenant_created
                    ON context_units_temporal(tenant_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS temporal_episodes (
                    id          TEXT        PRIMARY KEY,
                    tenant_id   TEXT        NOT NULL,
                    started_at  TIMESTAMPTZ NOT NULL,
                    ended_at    TIMESTAMPTZ
                );

                CREATE INDEX IF NOT EXISTS idx_episodes_tenant
                    ON temporal_episodes(tenant_id, started_at);
                """
            )

    async def insert_context_unit_temporal(self, unit: ContextUnit) -> None:
        """Insert a ContextUnit temporal record (idempotent)."""
        if self._pool is None:
            return
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO context_units_temporal
                        (id, tenant_id, session_id, episode_id, window_id, created_at)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    unit.id,
                    unit.tenant_id,
                    unit.session_id,
                    unit.episode_id,
                    unit.window_id,
                    unit.created,
                )
        except Exception:
            logger.exception(
                "temporal_insert_failed", extra={"context_id": unit.id, "tenant_id": unit.tenant_id}
            )

    async def query_episode_neighbors(
        self, episode_id: str, tenant_id: str, limit: int = 50
    ) -> list[str]:
        """Return context unit IDs in the same episode, ordered by recency."""
        if self._pool is None:
            return []
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT id FROM context_units_temporal
                    WHERE episode_id = $1 AND tenant_id = $2
                    ORDER BY created_at DESC LIMIT $3
                    """,
                    episode_id,
                    tenant_id,
                    limit,
                )
            return [row["id"] for row in rows]
        except Exception:
            logger.exception("query_episode_neighbors_failed")
            return []

    async def query_window_neighbors(
        self, window_id: str, tenant_id: str, limit: int = 20
    ) -> list[str]:
        """Return context unit IDs in the same window, ordered by recency."""
        if self._pool is None:
            return []
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT id FROM context_units_temporal
                    WHERE window_id = $1 AND tenant_id = $2
                    ORDER BY created_at DESC LIMIT $3
                    """,
                    window_id,
                    tenant_id,
                    limit,
                )
            return [row["id"] for row in rows]
        except Exception:
            logger.exception("query_window_neighbors_failed")
            return []

    async def query_turn_neighbors(
        self, turn_id: str, tenant_id: str, limit: int = 10
    ) -> list[str]:
        """Return context unit IDs for a specific turn."""
        if self._pool is None:
            return []
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT id FROM context_units_temporal
                    WHERE turn_id = $1 AND tenant_id = $2
                    ORDER BY created_at DESC LIMIT $3
                    """,
                    turn_id,
                    tenant_id,
                    limit,
                )
            return [row["id"] for row in rows]
        except Exception:
            logger.exception("query_turn_neighbors_failed")
            return []

    async def query_recent(self, tenant_id: str, limit: int = 20) -> list[str]:
        """Return the most recent context unit IDs for a tenant (fallback)."""
        if self._pool is None:
            return []
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT id FROM context_units_temporal
                    WHERE tenant_id = $1
                    ORDER BY created_at DESC LIMIT $2
                    """,
                    tenant_id,
                    limit,
                )
            return [row["id"] for row in rows]
        except Exception:
            logger.exception("query_recent_failed")
            return []

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None
