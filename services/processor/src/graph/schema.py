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
        """Run all constraint and index creation queries."""
        async with self._driver.session() as session:
            # Entity indexes (kept from V2)
            await self._create_unique_constraint(session)
            await self._create_type_index(session)
            await self._create_tenant_id_index(session)
            await self._create_confidence_index(session)
            await self._create_timestamp_index(session)
            await self._create_name_index(session)
            await self._create_aliases_index(session)
            # ContextUnit indexes (V3 Zero-Mem)
            await self._create_context_unit_constraint(session)
            await self._create_context_unit_tenant_index(session)
            await self._create_context_unit_source_index(session)
            await self._create_context_unit_created_index(session)
            await self._create_context_unit_composite_index(session)

        logger.info("graph_schema_initialized", extra={"labels": ["Entity", "ContextUnit"]})

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

    @staticmethod
    async def _create_name_index(session: AsyncSession) -> None:
        """Create a composite index on (tenant_id, type, name) for :Entity.

        Speeds up the structural resolver's name/alias lookup which always
        filters by tenant_id + type before comparing the name field.
        """
        cypher = (
            "CREATE INDEX entity_tenant_type_name IF NOT EXISTS "
            "FOR (n:Entity) ON (n.tenant_id, n.type, n.name)"
        )
        await session.run(cypher)
        logger.debug("index_created", extra={"index": "entity_tenant_type_name", "label": "Entity"})

    @staticmethod
    async def _create_aliases_index(session: AsyncSession) -> None:
        """Create an index on the aliases list property for :Entity."""
        cypher = "CREATE INDEX entity_aliases IF NOT EXISTS " "FOR (n:Entity) ON (n.aliases)"
        await session.run(cypher)
        logger.debug("index_created", extra={"index": "entity_aliases", "label": "Entity"})

    # ------------------------------------------------------------------
    # ContextUnit schema (V3 Zero-Mem)
    # ------------------------------------------------------------------

    @staticmethod
    async def _create_context_unit_constraint(session: AsyncSession) -> None:
        """Unique constraint on :ContextUnit id."""
        cypher = (
            "CREATE CONSTRAINT context_unit_id IF NOT EXISTS "
            "FOR (n:ContextUnit) REQUIRE n.id IS UNIQUE"
        )
        await session.run(cypher)
        logger.debug("constraint_created", extra={"constraint": "context_unit_id"})

    @staticmethod
    async def _create_context_unit_tenant_index(session: AsyncSession) -> None:
        cypher = (
            "CREATE INDEX context_unit_tenant_id IF NOT EXISTS "
            "FOR (n:ContextUnit) ON (n.tenant_id)"
        )
        await session.run(cypher)
        logger.debug("index_created", extra={"index": "context_unit_tenant_id"})

    @staticmethod
    async def _create_context_unit_source_index(session: AsyncSession) -> None:
        cypher = (
            "CREATE INDEX context_unit_source_id IF NOT EXISTS "
            "FOR (n:ContextUnit) ON (n.source_id)"
        )
        await session.run(cypher)
        logger.debug("index_created", extra={"index": "context_unit_source_id"})

    @staticmethod
    async def _create_context_unit_created_index(session: AsyncSession) -> None:
        cypher = (
            "CREATE INDEX context_unit_created IF NOT EXISTS " "FOR (n:ContextUnit) ON (n.created)"
        )
        await session.run(cypher)
        logger.debug("index_created", extra={"index": "context_unit_created"})

    @staticmethod
    async def _create_context_unit_composite_index(session: AsyncSession) -> None:
        """Composite index for temporal hierarchy queries: tenant + episode + created."""
        cypher = (
            "CREATE INDEX context_unit_tenant_episode_created IF NOT EXISTS "
            "FOR (n:ContextUnit) ON (n.tenant_id, n.episode_id, n.created)"
        )
        await session.run(cypher)
        logger.debug("index_created", extra={"index": "context_unit_tenant_episode_created"})
