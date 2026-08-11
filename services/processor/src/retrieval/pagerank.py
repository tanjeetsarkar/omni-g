"""Shared Personalized PageRank helper for retrieval and drilldown.

Replaces the removed ``apoc.algo.pageRankWithConfig`` procedure (deleted in
APOC 5.x / Neo4j 5.26) with an equivalent computation done in Python via
``networkx``. The k-hop subgraph is still fetched via ``apoc.path.subgraphNodes``
(still valid in APOC 5.x); PageRank itself runs on an in-memory
``networkx.DiGraph`` built from the returned nodes and their ``CO_OCCURRED_IN``
edges.

Used by:
  - ``src.retrieval.relational.RelationalRetriever._ppr_retrieve``
  - ``src.processor.main`` drilldown ``/query/expand`` endpoint
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import networkx as nx
import scipy.sparse  # noqa: F401  — pre-imported so the first pagerank call

# doesn't pay the ~400ms one-time scipy import cost inside the request path.
from .scored_context import ScoredContext

if TYPE_CHECKING:
    from neo4j import AsyncSession

logger = logging.getLogger(__name__)


async def pagerank_subgraph(
    session: AsyncSession,
    anchor_ids: list[str],
    tenant_id: str,
    d_max: int,
    gamma: float = 0.6,
    top_k: int = 10,
    iterations: int = 100,
) -> list[ScoredContext]:
    """Run Personalized PageRank over the k-hop subgraph around *anchor_ids*.

    Steps:
      1. Fetch the k-hop subgraph via ``apoc.path.subgraphNodes`` (APOC 5.x
         still supports this) and collect the returned nodes.
      2. Fetch ``CO_OCCURRED_IN`` edges between the returned nodes (Entity
         → ContextUnit and Entity ↔ Entity co-occurrence) so the PageRank
         graph reflects the same relationship filter the old APOC call used.
      3. Build a ``networkx.DiGraph`` and run ``nx.pagerank`` with
         ``alpha=gamma`` and ``max_iter=iterations``.
      4. Filter to ``ContextUnit`` nodes, sort by score descending, and
         return the top-*top_k* as :class:`ScoredContext` objects.

    Raises on any Cypher/networkx failure so callers can fall back to BFS.
    """
    # ── Step 1: fetch subgraph nodes ────────────────────────────────────
    subgraph_cypher = """
    MATCH (anchor:Entity)
    WHERE anchor.id IN $anchor_ids AND anchor.tenant_id = $tenant_id

    CALL apoc.path.subgraphNodes(anchor, {
        maxLevel: $d_max,
        relationshipFilter: 'CO_OCCURRED_IN',
        labelFilter: '+ContextUnit|+Entity'
    }) YIELD node

    WITH collect(DISTINCT node) AS sub_nodes
    UNWIND sub_nodes AS n
    RETURN
        n.id AS node_id,
        labels(n) AS labels,
        n.tenant_id AS node_tenant,
        n.text AS text
    """
    node_result = await session.run(
        subgraph_cypher,
        anchor_ids=anchor_ids,
        tenant_id=tenant_id,
        d_max=d_max,
    )
    node_rows = await node_result.data()

    if not node_rows:
        return []

    # ── Step 2: fetch CO_OCCURRED_IN edges between the returned nodes ───
    node_ids = [row["node_id"] for row in node_rows]
    edges_cypher = """
    MATCH (a)-[r:CO_OCCURRED_IN]->(b)
    WHERE a.id IN $node_ids AND b.id IN $node_ids
       AND a.tenant_id = $tenant_id AND b.tenant_id = $tenant_id
    RETURN a.id AS src, b.id AS dst
    """
    edge_result = await session.run(
        edges_cypher,
        node_ids=node_ids,
        tenant_id=tenant_id,
    )
    edge_rows = await edge_result.data()

    # ── Step 3: build graph + run PageRank ─────────────────────────────
    graph: nx.DiGraph = nx.DiGraph()
    for row in node_rows:
        graph.add_node(row["node_id"])
    for row in edge_rows:
        graph.add_edge(row["src"], row["dst"])

    # Personalize: seed mass on the anchor entities so PageRank is
    # "personalized" toward the query anchors (matches the old APOC
    # behaviour where the subgraph was rooted at the anchors).
    anchor_set = {aid for aid in anchor_ids if graph.has_node(aid)}
    if anchor_set:
        personalization = {nid: (1.0 if nid in anchor_set else 0.0) for nid in graph}
        total = sum(personalization.values())
        if total > 0:
            personalization = {nid: v / total for nid, v in personalization.items()}
        else:
            personalization = None
    else:
        personalization = None

    try:
        scores = nx.pagerank(
            graph,
            alpha=gamma,
            max_iter=iterations,
            personalization=personalization,
            dangling=personalization,
            tol=1e-4,
        )
    except nx.PowerIterationFailedConvergence:
        # Fall back to uniform scores if PageRank fails to converge.
        logger.warning(
            "pagerank_failed_convergence_using_uniform",
            extra={"tenant_id": tenant_id, "iterations": iterations},
        )
        scores = {nid: 1.0 / len(graph) for nid in graph} if graph else {}

    # ── Step 4: filter to ContextUnit nodes, sort, take top_k ───────────
    context_rows = [row for row in node_rows if "ContextUnit" in row["labels"]]
    results = [
        ScoredContext(
            context_id=row["node_id"],
            score=float(scores.get(row["node_id"], 0.0)),
            text=row.get("text") or "",
        )
        for row in context_rows
    ]
    results.sort(key=lambda r: r.score, reverse=True)
    return results[:top_k]
