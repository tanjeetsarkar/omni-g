from __future__ import annotations

import logging

from neo4j import AsyncDriver, AsyncSession

logger = logging.getLogger(__name__)

# STIX SDO node labels that receive unique constraints and indexes.
_STIX_LABELS: list[str] = [
    "ThreatActor",
    "Malware",
    "Identity",
    "AttackPattern",
    "Campaign",
    "Indicator",
    "Location",
]


class GraphSchemaManager:
    """Initialise the Neo4j schema required by the Omni-G Processor.

    Call :meth:`initialize` once at service startup (idempotent — all
    Cypher statements use ``IF NOT EXISTS``).
    """

    def __init__(self, driver: AsyncDriver) -> None:
        self._driver = driver

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Run all constraint and index creation queries."""
        async with self._driver.session() as session:
            for label in _STIX_LABELS:
                await self._create_unique_constraint(session, label)
                await self._create_tenant_id_index(session, label)
                await self._create_confidence_index(session, label)
                await self._create_timestamp_index(session, label)

        logger.info(
            "graph_schema_initialized",
            extra={"labels": _STIX_LABELS},
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _create_unique_constraint(session: AsyncSession, label: str) -> None:
        """CREATE CONSTRAINT … REQUIRE n.id IS UNIQUE for *label*."""
        constraint_name = f"stix_{label.lower()}_id"
        cypher = (
            f"CREATE CONSTRAINT {constraint_name} IF NOT EXISTS "
            f"FOR (n:{label}) REQUIRE n.id IS UNIQUE"
        )
        await session.run(cypher)
        logger.debug(
            "constraint_created",
            extra={"constraint": constraint_name, "label": label},
        )

    @staticmethod
    async def _create_tenant_id_index(session: AsyncSession, label: str) -> None:
        """Create a composite index on (id, tenant_id) for *label*."""
        index_name = f"stix_{label.lower()}_tenant"
        cypher = (
            f"CREATE INDEX {index_name} IF NOT EXISTS "
            f"FOR (n:{label}) ON (n.id, n.tenant_id)"
        )
        await session.run(cypher)
        logger.debug(
            "index_created",
            extra={"index": index_name, "label": label},
        )

    @staticmethod
    async def _create_confidence_index(session: AsyncSession, label: str) -> None:
        """Create an index on confidence for *label*."""
        index_name = f"stix_{label.lower()}_confidence"
        cypher = (
            f"CREATE INDEX {index_name} IF NOT EXISTS "
            f"FOR (n:{label}) ON (n.confidence)"
        )
        await session.run(cypher)
        logger.debug(
            "index_created",
            extra={"index": index_name, "label": label},
        )

    @staticmethod
    async def _create_timestamp_index(session: AsyncSession, label: str) -> None:
        """Create a composite index on (created, modified) for *label*."""
        index_name = f"stix_{label.lower()}_timestamps"
        cypher = (
            f"CREATE INDEX {index_name} IF NOT EXISTS "
            f"FOR (n:{label}) ON (n.created, n.modified)"
        )
        await session.run(cypher)
        logger.debug(
            "index_created",
            extra={"index": index_name, "label": label},
        )
