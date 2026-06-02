from __future__ import annotations

import logging

from neo4j import AsyncDriver, AsyncSession

logger = logging.getLogger(__name__)


class GraphSchemaManager:
    """Initialise the Neo4j schema required by the Omni-G Processor.

    All entities share a single :Entity label with an open-ended ``type``
    property (e.g. "Person", "Organization", "Event").  An additional label
    matching the PascalCase type string is added by the persistence layer.

    Call :meth:`initialize` once at service startup (idempotent — all
    Cypher statements use ``IF NOT EXISTS``).
    """

    def __init__(self, driver: AsyncDriver) -> None:
        self._driver = driver

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Run all constraint and index creation queries for the :Entity label."""
        async with self._driver.session() as session:
            await self._create_unique_constraint(session)
            await self._create_type_index(session)
            await self._create_tenant_id_index(session)
            await self._create_confidence_index(session)
            await self._create_timestamp_index(session)

        logger.info("graph_schema_initialized", extra={"label": "Entity"})

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _create_unique_constraint(session: AsyncSession) -> None:
        """CREATE CONSTRAINT … REQUIRE n.id IS UNIQUE for :Entity."""
        cypher = (
            "CREATE CONSTRAINT entity_id IF NOT EXISTS " "FOR (n:Entity) REQUIRE n.id IS UNIQUE"
        )
        await session.run(cypher)
        logger.debug("constraint_created", extra={"constraint": "entity_id", "label": "Entity"})

    @staticmethod
    async def _create_type_index(session: AsyncSession) -> None:
        """Create an index on (type) for :Entity."""
        cypher = "CREATE INDEX entity_type IF NOT EXISTS " "FOR (n:Entity) ON (n.type)"
        await session.run(cypher)
        logger.debug("index_created", extra={"index": "entity_type", "label": "Entity"})

    @staticmethod
    async def _create_tenant_id_index(session: AsyncSession) -> None:
        """Create an index on (tenant_id) for :Entity."""
        cypher = "CREATE INDEX entity_tenant_id IF NOT EXISTS " "FOR (n:Entity) ON (n.tenant_id)"
        await session.run(cypher)
        logger.debug("index_created", extra={"index": "entity_tenant_id", "label": "Entity"})

    @staticmethod
    async def _create_confidence_index(session: AsyncSession) -> None:
        """Create an index on (confidence) for :Entity."""
        cypher = "CREATE INDEX entity_confidence IF NOT EXISTS " "FOR (n:Entity) ON (n.confidence)"
        await session.run(cypher)
        logger.debug("index_created", extra={"index": "entity_confidence", "label": "Entity"})

    @staticmethod
    async def _create_timestamp_index(session: AsyncSession) -> None:
        """Create a composite index on (created, modified) for :Entity."""
        cypher = (
            "CREATE INDEX entity_timestamps IF NOT EXISTS "
            "FOR (n:Entity) ON (n.created, n.modified)"
        )
        await session.run(cypher)
        logger.debug("index_created", extra={"index": "entity_timestamps", "label": "Entity"})
