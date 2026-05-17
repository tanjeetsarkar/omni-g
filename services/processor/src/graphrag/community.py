from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

from neo4j import AsyncDriver
from prometheus_client import Counter, Histogram

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------

COMMUNITY_DETECTION_LATENCY = Histogram(
    "processor_community_detection_latency_seconds",
    "Latency of community detection runs",
    ["algorithm", "tenant_id"],
    buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
)

COMMUNITY_DETECTION_ERRORS = Counter(
    "processor_community_detection_errors_total",
    "Total community detection failures",
    ["algorithm", "tenant_id"],
)

COMMUNITY_SIZE = Histogram(
    "processor_community_size",
    "Distribution of community sizes (number of member entities)",
    buckets=[1, 2, 5, 10, 20, 50, 100, 500],
)


# ---------------------------------------------------------------------------
# Data transfer object
# ---------------------------------------------------------------------------


@dataclass
class CommunityResult:
    """Result of one detected community."""

    community_id: int
    entity_ids: list[str]
    tenant_id: str
    algorithm: str
    computed_at: datetime = field(default_factory=lambda: datetime.now(UTC))


# ---------------------------------------------------------------------------
# Python-side connected-components fallback
# ---------------------------------------------------------------------------


def _connected_components(edges: list[tuple[str, str]]) -> dict[str, int]:
    """Union-Find connected-components for use when GDS is unavailable.

    Args:
        edges: List of (source_id, target_id) pairs.

    Returns:
        Mapping of entity_id → community_id (0-based integer).
    """
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        if x not in parent:
            parent[x] = x
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]

    def union(a: str, b: str) -> None:
        pa, pb = find(a), find(b)
        if pa != pb:
            parent[pa] = pb

    for src, tgt in edges:
        union(src, tgt)

    # Assign deterministic integer community IDs
    root_to_id: dict[str, int] = {}
    assignment: dict[str, int] = {}
    for node in set(n for pair in edges for n in pair):
        root = find(node)
        if root not in root_to_id:
            root_to_id[root] = len(root_to_id)
        assignment[node] = root_to_id[root]

    return assignment


# ---------------------------------------------------------------------------
# CommunityDetector
# ---------------------------------------------------------------------------


class CommunityDetector:
    """Detect communities in the STIX knowledge graph.

    Attempts to use the Neo4j GDS ``leiden`` (or ``louvain``) algorithm.
    Falls back to a pure-Python connected-components implementation if GDS
    is unavailable.
    """

    def __init__(self, driver: AsyncDriver) -> None:
        self._driver = driver

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def detect_communities(
        self,
        tenant_id: str,
        *,
        algorithm: str = "leiden",
    ) -> list[CommunityResult]:
        """Run community detection for all entities in *tenant_id*.

        Tries GDS ``leiden`` / ``louvain`` first; falls back to Python-side
        connected-components if the GDS plugin is not available.
        """
        t0 = time.perf_counter()
        try:
            communities = await self._detect_via_gds(tenant_id, algorithm=algorithm)
        except Exception as gds_err:
            logger.warning(
                "gds_unavailable_fallback",
                extra={
                    "tenant_id": tenant_id,
                    "algorithm": algorithm,
                    "error": str(gds_err),
                },
            )
            COMMUNITY_DETECTION_ERRORS.labels(algorithm=algorithm, tenant_id=tenant_id).inc()
            communities = await self._detect_via_python_cc(tenant_id)

        COMMUNITY_DETECTION_LATENCY.labels(algorithm=algorithm, tenant_id=tenant_id).observe(
            time.perf_counter() - t0
        )

        for c in communities:
            COMMUNITY_SIZE.observe(len(c.entity_ids))

        logger.info(
            "communities_detected",
            extra={
                "tenant_id": tenant_id,
                "algorithm": algorithm,
                "community_count": len(communities),
            },
        )
        return communities

    async def detect_communities_for_entity(
        self,
        entity_id: str,
        tenant_id: str,
        *,
        hop_depth: int = 2,
    ) -> list[CommunityResult]:
        """Incremental: run community detection on the subgraph around *entity_id*.

        Fetches nodes within *hop_depth* hops from *entity_id*, then runs
        Python-side connected-components on that subgraph only.
        """
        t0 = time.perf_counter()
        algorithm = "python_cc_incremental"

        async with self._driver.session() as session:
            result = await session.run(
                "MATCH (origin:STIXEntity {id: $entity_id, tenant_id: $tenant_id})"
                f"-[*1..{hop_depth}]-(neighbor:STIXEntity {{tenant_id: $tenant_id}}) "
                "RETURN DISTINCT neighbor.id AS nid",
                entity_id=entity_id,
                tenant_id=tenant_id,
            )
            records = await result.data()

        subgraph_ids = {entity_id} | {r["nid"] for r in records}

        # Fetch edges within the subgraph
        async with self._driver.session() as session:
            edge_result = await session.run(
                "MATCH (a:STIXEntity {tenant_id: $tenant_id})"
                "-[r]-(b:STIXEntity {tenant_id: $tenant_id}) "
                "WHERE a.id IN $ids AND b.id IN $ids "
                "RETURN a.id AS source_id, b.id AS target_id",
                tenant_id=tenant_id,
                ids=list(subgraph_ids),
            )
            edge_records = await edge_result.data()

        edges = [(r["source_id"], r["target_id"]) for r in edge_records]
        # Add isolated node (entity_id itself) even if no edges found
        if not edges:
            edges = [(entity_id, entity_id)]

        assignment = _connected_components(edges)
        communities = _build_communities(assignment, tenant_id, algorithm)

        COMMUNITY_DETECTION_LATENCY.labels(algorithm=algorithm, tenant_id=tenant_id).observe(
            time.perf_counter() - t0
        )

        for c in communities:
            COMMUNITY_SIZE.observe(len(c.entity_ids))

        logger.debug(
            "incremental_communities_detected",
            extra={
                "entity_id": entity_id,
                "tenant_id": tenant_id,
                "hop_depth": hop_depth,
                "community_count": len(communities),
            },
        )
        return communities

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _detect_via_gds(self, tenant_id: str, *, algorithm: str) -> list[CommunityResult]:
        """Attempt GDS community detection.  Raises if GDS is unavailable."""
        async with self._driver.session() as session:
            # Project in-memory graph
            project_cypher = (
                "CALL gds.graph.project.cypher("
                "  'omni_g_graph',"
                "  'MATCH (n:STIXEntity {tenant_id: $tenant_id}) RETURN id(n) AS id',"
                "  'MATCH (n:STIXEntity {tenant_id: $tenant_id})-[r]->"
                "(m:STIXEntity {tenant_id: $tenant_id}) "
                "RETURN id(n) AS source, id(m) AS target',"
                "  {parameters: {tenant_id: $tenant_id}}"
                ") YIELD graphName"
            )
            await session.run(project_cypher, tenant_id=tenant_id)

            # Choose GDS procedure
            if algorithm == "leiden":
                gds_cypher = (
                    "CALL gds.leiden.stream('omni_g_graph') "
                    "YIELD nodeId, communityId "
                    "RETURN gds.util.asNode(nodeId).id AS entity_id, communityId"
                )
            else:
                gds_cypher = (
                    "CALL gds.louvain.stream('omni_g_graph') "
                    "YIELD nodeId, communityId "
                    "RETURN gds.util.asNode(nodeId).id AS entity_id, communityId"
                )

            result = await session.run(gds_cypher)
            records = await result.data()

            # Drop the projected graph
            await session.run("CALL gds.graph.drop('omni_g_graph', false) YIELD graphName")

        assignment: dict[str, int] = {r["entity_id"]: r["communityId"] for r in records}
        return _build_communities(assignment, tenant_id, algorithm)

    async def _detect_via_python_cc(self, tenant_id: str) -> list[CommunityResult]:
        """Python-side connected-components fallback."""
        algorithm = "python_cc"
        async with self._driver.session() as session:
            result = await session.run(
                "MATCH (n:STIXEntity {tenant_id: $tenant_id})"
                "-[r]-(m:STIXEntity {tenant_id: $tenant_id}) "
                "RETURN n.id AS source_id, m.id AS target_id",
                tenant_id=tenant_id,
            )
            records = await result.data()

        edges = [(r["source_id"], r["target_id"]) for r in records]

        if not edges:
            # Fetch isolated nodes
            async with self._driver.session() as session:
                iso_result = await session.run(
                    "MATCH (n:STIXEntity {tenant_id: $tenant_id}) RETURN n.id AS nid",
                    tenant_id=tenant_id,
                )
                iso_records = await iso_result.data()
            assignment: dict[str, int] = {r["nid"]: idx for idx, r in enumerate(iso_records)}
        else:
            assignment = _connected_components(edges)

        return _build_communities(assignment, tenant_id, algorithm)


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


def _build_communities(
    assignment: dict[str, int],
    tenant_id: str,
    algorithm: str,
) -> list[CommunityResult]:
    """Convert a node→community_id mapping into :class:`CommunityResult` objects."""
    groups: dict[int, list[str]] = {}
    for entity_id, community_id in assignment.items():
        groups.setdefault(community_id, []).append(entity_id)

    now = datetime.now(UTC)
    return [
        CommunityResult(
            community_id=cid,
            entity_ids=members,
            tenant_id=tenant_id,
            algorithm=algorithm,
            computed_at=now,
        )
        for cid, members in groups.items()
    ]
