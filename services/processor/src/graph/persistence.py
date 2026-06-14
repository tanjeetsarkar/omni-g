from __future__ import annotations

import logging
import re
import time
from typing import Any

from neo4j import AsyncDriver, AsyncSession
from prometheus_client import Counter, Histogram

from ..models.entities import Entity, ExtractionResult, Relationship

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------

GRAPH_WRITE_LATENCY = Histogram(
    "processor_graph_write_latency_seconds",
    "Latency of Neo4j graph write operations",
    ["operation"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5],
)

GRAPH_WRITE_ERRORS = Counter(
    "processor_graph_write_errors_total",
    "Total Neo4j graph write failures",
    ["operation"],
)

# ---------------------------------------------------------------------------
# STIX relationship type → Neo4j edge type mapping
# ---------------------------------------------------------------------------

_REL_TYPE_MAP: dict[str, str] = {
    "attributed-to": "ATTRIBUTED_TO",
    "targets": "TARGETS",
    "uses": "USES",
    "located-at": "LOCATED_AT",
    "related-to": "RELATED_TO",
}


def _map_relationship_type(stix_rel_type: str) -> str:
    """Map a STIX relationship_type string to a Neo4j edge label.

    Known types are looked up from :data:`_REL_TYPE_MAP`.  Unknown types are
    upper-cased and have hyphens replaced with underscores, e.g.
    ``"attributed-to"`` → ``"ATTRIBUTED_TO"``.
    """
    if stix_rel_type in _REL_TYPE_MAP:
        return _REL_TYPE_MAP[stix_rel_type]
    return re.sub(r"[^a-zA-Z0-9_]", "_", stix_rel_type).upper()


def _safe_label(s: str) -> str:
    """Sanitize *s* so it can be used safely as a Neo4j node label."""
    safe = re.sub(r"[^a-zA-Z0-9_]", "_", s)
    if safe and safe[0].isdigit():
        safe = "L_" + safe
    return safe


def _props_from_entity(entity: Entity, tenant_id: str) -> dict[str, Any]:
    """Flatten an Entity into Neo4j-compatible node properties."""
    import json
    from datetime import datetime

    props: dict[str, Any] = {}
    for k, v in entity.model_dump().items():
        if isinstance(v, bool):
            props[k] = v
        elif isinstance(v, str | int | float):
            props[k] = v
        elif v is None:
            props[k] = v
        elif isinstance(v, datetime):
            props[k] = v.isoformat()
        else:
            props[k] = json.dumps(v, default=str)
    # Always override with the authoritative tenant_id from the pipeline.
    # Entity.tenant_id defaults to "" at extraction time and must not be
    # used as the stored value.
    props["tenant_id"] = tenant_id
    return props


# ---------------------------------------------------------------------------
# GraphPersistenceService
# ---------------------------------------------------------------------------


class GraphPersistenceService:
    """Write generic entities and relationships to Neo4j with transaction management.

    All write methods accept an optional *session* parameter.  When
    :meth:`persist_extraction` is used the caller should omit *session*;
    the method opens its own session and wraps everything in a single
    transaction that rolls back automatically if any write fails.
    """

    def __init__(self, driver: AsyncDriver) -> None:
        self._driver = driver

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def upsert_entity(
        self,
        entity: Entity,
        tenant_id: str,
        *,
        session: AsyncSession | None = None,
    ) -> str:
        """MERGE entity node by id and SET all properties.

        Returns the canonical entity id of the persisted node.
        """
        t0 = time.perf_counter()
        label = _safe_label(entity.type)
        tenant_label = _safe_label(tenant_id)
        props = _props_from_entity(entity, tenant_id)

        cypher = (
            f"MERGE (n:Entity:{label}:{tenant_label} {{id: $id}}) "
            "ON CREATE SET n += $props "
            "ON MATCH SET n.modified = $modified, "
            "             n.name = $name, "
            "             n.confidence = $confidence, "
            "             n.description = $description, "
            "             n.properties = $properties_json "
            "RETURN n.id AS entity_id"
        )

        import json

        try:
            params: dict[str, Any] = {
                "id": entity.id,
                "props": props,
                "modified": props.get("modified", ""),
                "name": entity.name,
                "confidence": entity.confidence,
                "description": entity.description,
                "properties_json": json.dumps(entity.properties, default=str),
            }
            if session is not None:
                result = await session.run(cypher, **params)
                record = await result.single()
            else:
                async with self._driver.session() as s:
                    result = await s.run(cypher, **params)
                    record = await result.single()

            entity_id: str = record["entity_id"] if record else entity.id
            GRAPH_WRITE_LATENCY.labels(operation="upsert_entity").observe(time.perf_counter() - t0)
            logger.debug(
                "entity_persisted",
                extra={
                    "entity_id": entity_id,
                    "label": label,
                    "tenant_id": tenant_id,
                },
            )
            return entity_id

        except Exception:
            GRAPH_WRITE_ERRORS.labels(operation="upsert_entity").inc()
            logger.exception(
                "entity_persist_failed",
                extra={"entity_id": entity.id, "label": label, "tenant_id": tenant_id},
            )
            raise

    async def upsert_relationship(
        self,
        relationship: Relationship,
        tenant_id: str,
        *,
        session: AsyncSession | None = None,
    ) -> None:
        """MERGE a generic relationship edge between source and target nodes."""
        t0 = time.perf_counter()
        edge_type = _map_relationship_type(relationship.type)

        cypher = (
            "MATCH (src {id: $source_id}), (tgt {id: $target_id}) "
            f"MERGE (src)-[r:{edge_type}]->(tgt) "
            "SET r.id = $rel_id, "
            "    r.tenant_id = $tenant_id, "
            "    r.confidence = $confidence, "
            "    r.created = $created, "
            "    r.modified = $modified"
        )
        params: dict[str, Any] = {
            "source_id": relationship.source_ref,
            "target_id": relationship.target_ref,
            "rel_id": relationship.id,
            "tenant_id": tenant_id,
            "confidence": relationship.confidence,
            "created": relationship.created.isoformat(),
            "modified": relationship.modified.isoformat(),
        }

        try:
            if session is not None:
                await session.run(cypher, **params)
            else:
                async with self._driver.session() as s:
                    await s.run(cypher, **params)

            GRAPH_WRITE_LATENCY.labels(operation="upsert_relationship").observe(
                time.perf_counter() - t0
            )
            logger.debug(
                "relationship_persisted",
                extra={
                    "rel_id": relationship.id,
                    "edge_type": edge_type,
                    "tenant_id": tenant_id,
                },
            )

        except Exception:
            GRAPH_WRITE_ERRORS.labels(operation="upsert_relationship").inc()
            logger.exception(
                "relationship_persist_failed",
                extra={
                    "rel_id": relationship.id,
                    "edge_type": edge_type,
                    "tenant_id": tenant_id,
                },
            )
            raise

    async def persist_extraction(
        self,
        result: ExtractionResult,
        tenant_id: str,
    ) -> list[str]:
        """Persist all entities + relationships from *result* in one transaction.

        The entire transaction is rolled back automatically if any write fails.
        Returns the list of persisted entity IDs.
        """
        import json

        t0 = time.perf_counter()
        persisted_ids: list[str] = []
        tenant_label = _safe_label(tenant_id)

        try:
            async with self._driver.session() as session:
                async with await session.begin_transaction() as tx:
                    # Persist all entity nodes first
                    for entity in result.entities:
                        label = _safe_label(entity.type)
                        props = _props_from_entity(entity, tenant_id)
                        cypher = (
                            f"MERGE (n:Entity:{label}:{tenant_label} {{id: $id}}) "
                            "ON CREATE SET n += $props "
                            "ON MATCH SET n.modified = $modified, "
                            "             n.name = $name, "
                            "             n.confidence = $confidence, "
                            "             n.description = $description, "
                            "             n.properties = $properties_json, "
                            "             n.tenant_id = $tenant_id, "
                            "             n.source_id = $source_id "
                            "RETURN n.id AS entity_id"
                        )
                        query_result = await tx.run(
                            cypher,
                            id=entity.id,
                            props=props,
                            modified=props.get("modified", ""),
                            name=entity.name,
                            confidence=entity.confidence,
                            description=entity.description,
                            properties_json=json.dumps(entity.properties, default=str),
                            tenant_id=tenant_id,
                            source_id=entity.source_id,
                        )
                        record = await query_result.single()
                        eid: str = record["entity_id"] if record else entity.id
                        persisted_ids.append(eid)

                    # Persist all relationship edges.
                    # Both endpoints must be Entity nodes belonging to the same
                    # tenant — enforced at the Cypher level to prevent
                    # cross-tenant edges and phantom non-Entity matches.
                    for rel in result.relationships:
                        edge_type = _map_relationship_type(rel.type)
                        rel_cypher = (
                            "MATCH (src:Entity {id: $source_id}), "
                            "      (tgt:Entity {id: $target_id}) "
                            "WHERE src.tenant_id = $tenant_id "
                            "  AND tgt.tenant_id = $tenant_id "
                            f"MERGE (src)-[r:{edge_type}]->(tgt) "
                            "SET r.id = $rel_id, "
                            "    r.tenant_id = $tenant_id, "
                            "    r.confidence = $confidence, "
                            "    r.created = $created, "
                            "    r.modified = $modified"
                        )
                        await tx.run(
                            rel_cypher,
                            source_id=rel.source_ref,
                            target_id=rel.target_ref,
                            rel_id=rel.id,
                            tenant_id=tenant_id,
                            confidence=rel.confidence,
                            created=rel.created.isoformat(),
                            modified=rel.modified.isoformat(),
                        )

                    await tx.commit()

            GRAPH_WRITE_LATENCY.labels(operation="persist_extraction").observe(
                time.perf_counter() - t0
            )
            logger.info(
                "extraction_persisted",
                extra={
                    "source_event_id": result.source_event_id,
                    "tenant_id": tenant_id,
                    "entity_count": len(persisted_ids),
                    "relationship_count": len(result.relationships),
                },
            )
            return persisted_ids

        except Exception:
            GRAPH_WRITE_ERRORS.labels(operation="persist_extraction").inc()
            logger.exception(
                "extraction_persist_failed",
                extra={
                    "source_event_id": result.source_event_id,
                    "tenant_id": tenant_id,
                },
            )
            raise

    async def search_entities(
        self,
        tenant_id: str,
        limit: int = 20,
    ) -> list[Entity]:
        """Return the most-recently modified entities for a tenant.

        Used as the fallback path in the /search endpoint when Qdrant is
        unavailable or no query embedding can be produced.
        """
        from datetime import UTC
        from datetime import datetime as _dt

        try:
            async with self._driver.session() as session:
                result = await session.run(
                    """
                    MATCH (e:Entity)
                    WHERE e.tenant_id = $tenant_id OR (e.tenant_id = '' AND $tenant_id <> '')
                    RETURN e
                    ORDER BY e.modified DESC
                    LIMIT $limit
                    """,
                    tenant_id=tenant_id,
                    limit=limit,
                )
                rows = await result.data()
        except Exception:
            logger.exception("search_entities_failed", extra={"tenant_id": tenant_id})
            return []

        entities: list[Entity] = []
        now = _dt.now(UTC)
        for row in rows:
            node = row.get("e", {})
            try:
                entities.append(
                    Entity(
                        id=node.get("id", ""),
                        type=node.get("type", "Unknown"),
                        name=node.get("name", "Unknown"),
                        description=node.get("description"),
                        properties={},
                        confidence=float(node.get("confidence", 0.5)),
                        tenant_id=node.get("tenant_id", tenant_id),
                        source_id=node.get("source_id"),
                        created=node.get("created") or now,
                        modified=node.get("modified") or now,
                    )
                )
            except Exception:
                logger.debug("search_entities_skip_node", extra={"node": node})
        return entities

    async def fetch_relationships_for_entities(
        self,
        entity_ids: list[str],
    ) -> list[dict[str, Any]]:
        """Return all relationships where both endpoints are in *entity_ids*.

        Returns plain dicts (not Relationship model instances) because the
        stored ``created``/``modified`` fields may be ISO-string properties
        that need no further coercion for JSON serialization.
        """
        if not entity_ids:
            return []
        try:
            async with self._driver.session() as session:
                result = await session.run(
                    """
                    MATCH (src:Entity)-[r]->(tgt:Entity)
                    WHERE src.id IN $entity_ids AND tgt.id IN $entity_ids
                    RETURN
                        coalesce(r.id, '') AS id,
                        type(r)            AS type,
                        src.id             AS source_ref,
                        tgt.id             AS target_ref,
                        coalesce(r.confidence, 0.5) AS confidence,
                        coalesce(r.tenant_id, '')   AS tenant_id,
                        coalesce(r.created,  '')    AS created,
                        coalesce(r.modified, '')    AS modified
                    """,
                    entity_ids=entity_ids,
                )
                rows = await result.data()
        except Exception:
            logger.exception(
                "fetch_relationships_failed",
                extra={"entity_count": len(entity_ids)},
            )
            return []

        rels: list[dict[str, Any]] = []
        for row in rows:
            rel_id = row.get("id") or (
                f"rel--{row.get('source_ref','')}-{row.get('type','')}-{row.get('target_ref','')}"
            )
            rels.append(
                {
                    "id": rel_id,
                    "type": row.get("type", "RELATED_TO"),
                    "source_ref": row.get("source_ref", ""),
                    "target_ref": row.get("target_ref", ""),
                    "confidence": float(row.get("confidence", 0.5)),
                    "tenant_id": row.get("tenant_id", ""),
                    "created": row.get("created", ""),
                    "modified": row.get("modified", ""),
                }
            )
        return rels

    async def fetch_neighbor_entities(
        self,
        entity_ids: list[str],
    ) -> list[Entity]:
        """Return 1-hop outgoing neighbours of *entity_ids* not already in that set.

        Used by the search endpoint to expand the result set before building
        the relationship graph, so that edges from matched entities to their
        direct neighbours are also rendered in the Delivery canvas.
        """
        if not entity_ids:
            return []
        try:
            async with self._driver.session() as session:
                result = await session.run(
                    """
                    MATCH (src:Entity)-[]->(tgt:Entity)
                    WHERE src.id IN $entity_ids AND NOT tgt.id IN $entity_ids
                    RETURN DISTINCT tgt AS e
                    LIMIT 100
                    """,
                    entity_ids=entity_ids,
                )
                rows = await result.data()
        except Exception:
            logger.exception(
                "fetch_neighbors_failed",
                extra={"entity_count": len(entity_ids)},
            )
            return []

        entities: list[Entity] = []
        from datetime import UTC
        from datetime import datetime as _dt_nb

        now = _dt_nb.now(UTC)
        for row in rows:
            node = row.get("e", {})
            try:
                entities.append(
                    Entity(
                        id=node.get("id", ""),
                        type=node.get("type", "Unknown"),
                        name=node.get("name", "Unknown"),
                        description=node.get("description"),
                        properties={},
                        confidence=float(node.get("confidence", 0.5)),
                        tenant_id=node.get("tenant_id", ""),
                        source_id=node.get("source_id"),
                        created=node.get("created") or now,
                        modified=node.get("modified") or now,
                    )
                )
            except Exception:
                logger.debug("fetch_neighbors_skip_node", extra={"node": node})
        return entities
