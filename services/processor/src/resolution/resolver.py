from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from datetime import UTC, datetime
from typing import Any

from neo4j import AsyncDriver
from prometheus_client import Counter, Histogram
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from ..models.stix import STIXObject
from .models import CandidateMatch, ResolutionDecision, ResolutionResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level config
# ---------------------------------------------------------------------------

EMBEDDING_DIM: int = int(os.getenv("EMBEDDING_DIM", "768"))

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------

RESOLUTION_DECISIONS = Counter(
    "processor_resolution_decisions_total",
    "Total entity resolution decisions by outcome",
    ["decision", "tenant_id"],
)

RESOLUTION_LATENCY = Histogram(
    "processor_resolution_latency_seconds",
    "End-to-end latency of entity resolution (vector + structural + decision)",
    ["tenant_id"],
)

FALSE_POSITIVE_ALERTS = Counter(
    "processor_false_positive_alerts_total",
    "Ambiguous resolution decisions flagged for analyst review (proxy for false positives)",
    ["tenant_id"],
)

SAME_AS_MERGES = Counter(
    "processor_same_as_merges_total",
    "Entities automatically merged via SAME_AS relationship",
    ["tenant_id"],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_label(s: str) -> str:
    """Sanitize *s* so it can be used safely as a Neo4j node label.

    Replaces any character outside ``[a-zA-Z0-9_]`` with ``_`` and prepends
    ``L_`` if the first character would be a digit.
    """
    safe = re.sub(r"[^a-zA-Z0-9_]", "_", s)
    if safe and safe[0].isdigit():
        safe = "L_" + safe
    return safe


def _stix_id_to_qdrant_id(stix_id: str) -> str:
    """Extract the UUID portion from a STIX ID for use as a Qdrant point ID.

    ``"threat-actor--550e8400-..."`` → ``"550e8400-..."``
    """
    parts = stix_id.split("--", 1)
    return parts[1] if len(parts) == 2 else stix_id  # noqa: PLR2004


def _get_entity_name(entity: STIXObject) -> str:
    """Return the ``name`` attribute of *entity*, or an empty string if absent."""
    name = getattr(entity, "name", None)
    return str(name) if name is not None else ""


def _get_entity_aliases(entity: STIXObject) -> list[str]:
    """Return the ``aliases`` attribute of *entity*, or an empty list if absent."""
    aliases = getattr(entity, "aliases", None)
    return list(aliases) if aliases else []


def _props_from_entity(entity: STIXObject, tenant_id: str) -> dict[str, Any]:
    """Flatten a STIXObject into Neo4j-compatible node properties.

    Complex nested types (lists, dicts) are serialised as JSON strings.
    ``datetime`` values are stored as ISO-8601 strings.
    """
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
# Core resolver
# ---------------------------------------------------------------------------


class EntityResolver:
    """Resolve incoming STIX entities against the knowledge graph.

    Two-stage matching pipeline
    ---------------------------
    1. **Vector blocking** (Qdrant semantic search) — fast approximate
       candidate retrieval using hash-based placeholder embeddings.
    2. **Graph structural matching** (Neo4j) — exact name / alias lookup
       plus co-occurrence analysis on relationship targets.

    Confidence tiers
    ----------------
    * ``score >= 0.95``        → :attr:`~.ResolutionDecision.AUTO_MERGE`
    * ``0.50 <= score < 0.95`` → :attr:`~.ResolutionDecision.AMBIGUOUS`
    * ``score < 0.50``         → :attr:`~.ResolutionDecision.NEW_ENTITY`
    """

    def __init__(
        self,
        neo4j_driver: AsyncDriver,
        qdrant_client: AsyncQdrantClient,
        embedding_dim: int = EMBEDDING_DIM,
    ) -> None:
        self._neo4j = neo4j_driver
        self._qdrant = qdrant_client
        self._embedding_dim = embedding_dim

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def resolve(self, tenant_id: str, entity: STIXObject) -> ResolutionResult:
        """Resolve *entity* against the knowledge graph and return a decision.

        Emits Prometheus metrics for latency and decision outcome.
        """
        t0 = time.perf_counter()
        try:
            vector_candidates = await self.find_candidates(tenant_id, entity)
            structural_candidates = await self.find_structural_matches(tenant_id, entity)
            result = self._apply_decision(
                vector_candidates + structural_candidates,
                entity,
            )
        finally:
            RESOLUTION_LATENCY.labels(tenant_id=tenant_id).observe(
                time.perf_counter() - t0
            )

        RESOLUTION_DECISIONS.labels(
            decision=result.decision.value,
            tenant_id=tenant_id,
        ).inc()

        if result.decision == ResolutionDecision.AMBIGUOUS:
            FALSE_POSITIVE_ALERTS.labels(tenant_id=tenant_id).inc()
        elif result.decision == ResolutionDecision.AUTO_MERGE:
            SAME_AS_MERGES.labels(tenant_id=tenant_id).inc()

        logger.info(
            "entity_resolved",
            extra={
                "tenant_id": tenant_id,
                "entity_id": entity.id,
                "decision": result.decision.value,
                "confidence": result.confidence_score,
                "matched": result.matched_entity_id,
            },
        )
        return result

    async def persist_entity(
        self,
        tenant_id: str,
        entity: STIXObject,
        resolution: ResolutionResult,
    ) -> str:
        """Persist *entity* to Neo4j according to the resolution decision.

        Returns the canonical entity ID used in the graph:
        * ``AUTO_MERGE``  → matched entity's ID (existing node updated in-place)
        * ``AMBIGUOUS``   → new node's ID (SAME_AS edge links it to the match)
        * ``NEW_ENTITY``  → new node's ID
        """
        decision = resolution.decision
        props = _props_from_entity(entity, tenant_id)
        type_label = _safe_label(entity.type.value)
        tenant_label = _safe_label(tenant_id)

        if decision == ResolutionDecision.NEW_ENTITY:
            return await self._create_node(
                entity.id, props, type_label, tenant_label
            )

        if decision == ResolutionDecision.AUTO_MERGE:
            matched_id = resolution.matched_entity_id or entity.id
            await self._update_node(matched_id, props)
            logger.info(
                "entity_auto_merged",
                extra={
                    "tenant_id": tenant_id,
                    "incoming_id": entity.id,
                    "canonical_id": matched_id,
                },
            )
            return matched_id

        # AMBIGUOUS: create new node + SAME_AS relationship to matched entity
        new_id = await self._create_node(entity.id, props, type_label, tenant_label)
        if resolution.matched_entity_id:
            await self._create_same_as(
                source_id=new_id,
                target_id=resolution.matched_entity_id,
                tenant_id=tenant_id,
                confidence=resolution.confidence_score,
            )
        return new_id

    async def resolve_and_persist(
        self, tenant_id: str, entity: STIXObject
    ) -> ResolutionResult:
        """Convenience: resolve *entity* then persist the result in one call."""
        result = await self.resolve(tenant_id, entity)
        await self.persist_entity(tenant_id, entity, result)
        return result

    # ------------------------------------------------------------------
    # Vector blocking (Qdrant)
    # ------------------------------------------------------------------

    async def find_candidates(
        self, tenant_id: str, entity: STIXObject
    ) -> list[CandidateMatch]:
        """Upsert entity embedding into Qdrant then return top-5 similar entities.

        The upsert step ensures that every entity flowing through the pipeline
        is indexed for future resolution passes.  The entity itself is filtered
        out of the returned candidates.
        """
        collection = f"entities_{tenant_id}"
        await self._ensure_collection(collection)

        text = f"{entity.type.value} {_get_entity_name(entity)}"
        vector = self._embed(text)
        qdrant_id = _stix_id_to_qdrant_id(entity.id)

        await self._qdrant.upsert(
            collection_name=collection,
            points=[
                PointStruct(
                    id=qdrant_id,
                    vector=vector,
                    payload={
                        "entity_id": entity.id,
                        "stix_type": entity.type.value,
                        "tenant_id": tenant_id,
                        "name": _get_entity_name(entity),
                    },
                )
            ],
        )

        raw = await self._qdrant.search(
            collection_name=collection,
            query_vector=vector,
            limit=5,
        )

        candidates: list[CandidateMatch] = []
        for point in raw:
            payload = point.payload or {}
            pid = str(payload.get("entity_id", ""))
            if pid and pid != entity.id:
                candidates.append(
                    CandidateMatch(
                        entity_id=pid,
                        score=float(point.score),
                        match_type="vector",
                    )
                )

        logger.debug(
            "vector_candidates_found",
            extra={
                "tenant_id": tenant_id,
                "entity_id": entity.id,
                "count": len(candidates),
            },
        )
        return candidates

    # ------------------------------------------------------------------
    # Graph structural matching (Neo4j)
    # ------------------------------------------------------------------

    async def find_structural_matches(
        self, tenant_id: str, entity: STIXObject
    ) -> list[CandidateMatch]:
        """Query Neo4j for structurally similar entities.

        Two sub-queries are executed:
        1. **Name / alias exact match** — score 1.0.
        2. **Co-occurrence** — entities sharing ≥ 2 common relationship
           targets — score proportional to shared-target count.
        """
        name = _get_entity_name(entity)
        stix_type = entity.type.value
        entity_id = entity.id

        candidates: list[CandidateMatch] = []

        async with self._neo4j.session() as session:
            # — Query 1: name / alias exact match ————————————————————————
            result1 = await session.run(
                """
                MATCH (e)
                WHERE e.tenant_id = $tenant_id
                  AND e.stix_type = $stix_type
                  AND e.id <> $entity_id
                  AND (
                    e.name = $name
                    OR $name IN coalesce(e.aliases_json, [])
                  )
                RETURN e.id AS entity_id, 1.0 AS score
                """,
                tenant_id=tenant_id,
                stix_type=stix_type,
                entity_id=entity_id,
                name=name,
            )
            rows1: list[dict[str, Any]] = await result1.data()
            for row in rows1:
                candidates.append(
                    CandidateMatch(
                        entity_id=str(row["entity_id"]),
                        score=float(row["score"]),
                        match_type="structural",
                    )
                )

            # — Query 2: co-occurrence (≥ 2 shared relationship targets) ——
            result2 = await session.run(
                """
                MATCH (existing)-[]->(shared)<-[]-(other {id: $entity_id})
                WHERE existing.tenant_id = $tenant_id
                  AND existing.id <> $entity_id
                WITH existing, count(DISTINCT shared) AS cnt
                WHERE cnt >= 2
                RETURN existing.id AS entity_id,
                       toFloat(cnt) / 10.0 AS score
                """,
                tenant_id=tenant_id,
                entity_id=entity_id,
            )
            rows2: list[dict[str, Any]] = await result2.data()
            for row in rows2:
                candidates.append(
                    CandidateMatch(
                        entity_id=str(row["entity_id"]),
                        score=min(float(row["score"]), 1.0),
                        match_type="structural",
                    )
                )

        logger.debug(
            "structural_candidates_found",
            extra={
                "tenant_id": tenant_id,
                "entity_id": entity_id,
                "count": len(candidates),
            },
        )
        return candidates

    # ------------------------------------------------------------------
    # Merge decision logic (pure, no I/O — easy to unit-test)
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_decision(
        candidates: list[CandidateMatch],
        entity: STIXObject,
    ) -> ResolutionResult:
        """Combine *candidates*, deduplicate by entity_id (keep max score),
        and apply confidence-tier thresholds to produce a :class:`ResolutionResult`.
        """
        # Deduplicate: for the same entity_id take the highest score seen
        best: dict[str, float] = {}
        for c in candidates:
            if c.entity_id not in best or c.score > best[c.entity_id]:
                best[c.entity_id] = c.score

        if not best:
            return ResolutionResult(
                decision=ResolutionDecision.NEW_ENTITY,
                matched_entity_id=None,
                confidence_score=0.0,
                entity=entity,
            )

        top_entity_id = max(best, key=lambda k: best[k])
        top_score = best[top_entity_id]

        if top_score >= 0.95:  # noqa: PLR2004
            return ResolutionResult(
                decision=ResolutionDecision.AUTO_MERGE,
                matched_entity_id=top_entity_id,
                confidence_score=top_score,
                entity=entity,
            )

        if top_score >= 0.50:  # noqa: PLR2004
            return ResolutionResult(
                decision=ResolutionDecision.AMBIGUOUS,
                matched_entity_id=top_entity_id,
                confidence_score=top_score,
                entity=entity,
            )

        return ResolutionResult(
            decision=ResolutionDecision.NEW_ENTITY,
            matched_entity_id=None,
            confidence_score=top_score,
            entity=entity,
        )

    # ------------------------------------------------------------------
    # Neo4j persistence helpers
    # ------------------------------------------------------------------

    async def _create_node(
        self,
        entity_id: str,
        props: dict[str, Any],
        type_label: str,
        tenant_label: str,
    ) -> str:
        """MERGE a new entity node in Neo4j and return its STIX ID."""
        cypher = (  # noqa: S608
            f"MERGE (e:Entity:{type_label}:{tenant_label} {{id: $id}}) "
            "ON CREATE SET e += $props, e.created_at = datetime() "
            "ON MATCH  SET e += $props, e.updated_at = datetime() "
            "RETURN e.id AS entity_id"
        )
        async with self._neo4j.session() as session:
            result = await session.run(cypher, id=entity_id, props=props)
            row: dict[str, Any] | None = await result.single()  # type: ignore[assignment]
        return str(row["entity_id"]) if row else entity_id

    async def _update_node(
        self,
        entity_id: str,
        props: dict[str, Any],
    ) -> None:
        """Update properties on an existing entity node (AUTO_MERGE path)."""
        async with self._neo4j.session() as session:
            await session.run(
                """
                MATCH (e {id: $id})
                SET e += $props, e.updated_at = datetime()
                """,
                id=entity_id,
                props=props,
            )

    async def _create_same_as(
        self,
        source_id: str,
        target_id: str,
        tenant_id: str,
        confidence: float,
    ) -> None:
        """Create or update a ``SAME_AS`` relationship between two nodes."""
        async with self._neo4j.session() as session:
            await session.run(
                """
                MATCH (a {id: $source_id}), (b {id: $target_id})
                MERGE (a)-[r:SAME_AS {tenant_id: $tenant_id}]->(b)
                SET r.confidence = $confidence, r.updated = $updated
                """,
                source_id=source_id,
                target_id=target_id,
                tenant_id=tenant_id,
                confidence=confidence,
                updated=datetime.now(UTC).isoformat(),
            )

    # ------------------------------------------------------------------
    # Qdrant collection management
    # ------------------------------------------------------------------

    async def _ensure_collection(self, collection_name: str) -> None:
        """Create the Qdrant collection if it does not already exist."""
        try:
            exists: bool = await self._qdrant.collection_exists(collection_name)
        except Exception:
            logger.warning(
                "collection_exists check failed for %s — assuming missing",
                collection_name,
            )
            exists = False

        if not exists:
            await self._qdrant.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(
                    size=self._embedding_dim,
                    distance=Distance.COSINE,
                ),
            )
            logger.info(
                "qdrant_collection_created",
                extra={"collection": collection_name, "dim": self._embedding_dim},
            )

    # ------------------------------------------------------------------
    # Embedding (placeholder — Phase 5 TODO)
    # ------------------------------------------------------------------

    @staticmethod
    def _embed(text: str) -> list[float]:
        """Delegate to the module-level :func:`_embed` function.

        .. todo:: Phase 5 — Replace with a real embedding model, e.g.
            ``sentence-transformers/all-MiniLM-L6-v2`` or a dedicated
            embedding API endpoint, for semantically meaningful similarity.
        """
        return _embed(text)


def _embed(text: str) -> list[float]:
    """Generate a deterministic hash-based float vector for *text*.

    Each byte of successive SHA-256 blocks is mapped linearly to
    the range ``[-1.0, 1.0]`` to fill a vector of length
    :data:`EMBEDDING_DIM`.

    .. todo:: Phase 5 — Replace with a real embedding model, e.g.
        ``sentence-transformers/all-MiniLM-L6-v2`` or a dedicated
        embedding API endpoint, for semantically meaningful similarity.
    """
    seed = hashlib.sha256(text.encode()).digest()
    floats: list[float] = []
    block_idx = 0
    while len(floats) < EMBEDDING_DIM:
        block = hashlib.sha256(seed + block_idx.to_bytes(4, "big")).digest()
        for byte in block:
            floats.append((byte - 127.5) / 127.5)
            if len(floats) >= EMBEDDING_DIM:
                break
        block_idx += 1
    return floats[:EMBEDDING_DIM]
