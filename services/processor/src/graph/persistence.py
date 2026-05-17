from __future__ import annotations

import logging
import re
import time
from typing import Any

from neo4j import AsyncDriver, AsyncSession
from prometheus_client import Counter, Histogram

from ..models.stix import ExtractionResult, Relationship, STIXObject

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


def _stix_type_to_label(stix_type_value: str) -> str:
    """Convert a STIX type string to a PascalCase Neo4j node label.

    Examples::

        "threat-actor"   → "ThreatActor"
        "attack-pattern" → "AttackPattern"
        "malware"        → "Malware"
    """
    return "".join(part.capitalize() for part in stix_type_value.split("-"))


def _props_from_entity(entity: STIXObject, tenant_id: str) -> dict[str, Any]:
    """Flatten a STIXObject into Neo4j-compatible node properties."""
    import json
    from datetime import datetime

    props: dict[str, Any] = {
        "tenant_id": tenant_id,
        "stix_type": entity.type.value,
    }
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
    return props


# ---------------------------------------------------------------------------
# GraphPersistenceService
# ---------------------------------------------------------------------------


class GraphPersistenceService:
    """Write STIX entities and relationships to Neo4j with transaction management.

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
        entity: STIXObject,
        tenant_id: str,
        *,
        session: AsyncSession | None = None,
    ) -> str:
        """MERGE entity node by id and SET all properties.

        Returns the canonical STIX id of the persisted node.
        """
        t0 = time.perf_counter()
        label = _stix_type_to_label(entity.type.value)
        props = _props_from_entity(entity, tenant_id)

        cypher = (
            f"MERGE (n:STIXEntity:{label} {{id: $id}}) "
            "ON CREATE SET n += $props "
            "ON MATCH SET n += $props "
            "RETURN n.id AS entity_id"
        )

        try:
            if session is not None:
                result = await session.run(cypher, id=entity.id, props=props)
                record = await result.single()
            else:
                async with self._driver.session() as s:
                    result = await s.run(cypher, id=entity.id, props=props)
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
        """MERGE a STIX relationship edge between source and target nodes."""
        t0 = time.perf_counter()
        edge_type = _map_relationship_type(relationship.relationship_type)

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
        t0 = time.perf_counter()
        persisted_ids: list[str] = []

        try:
            async with self._driver.session() as session:
                async with await session.begin_transaction() as tx:
                    # Persist all SDOs first
                    for entity in result.all_entities():
                        label = _stix_type_to_label(entity.type.value)
                        props = _props_from_entity(entity, tenant_id)
                        cypher = (
                            f"MERGE (n:STIXEntity:{label} {{id: $id}}) "
                            "ON CREATE SET n += $props "
                            "ON MATCH SET n += $props "
                            "RETURN n.id AS entity_id"
                        )
                        query_result = await tx.run(cypher, id=entity.id, props=props)
                        record = await query_result.single()
                        eid: str = record["entity_id"] if record else entity.id
                        persisted_ids.append(eid)

                    # Persist all SROs
                    for rel in result.relationships:
                        edge_type = _map_relationship_type(rel.relationship_type)
                        rel_cypher = (
                            "MATCH (src {id: $source_id}), (tgt {id: $target_id}) "
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
