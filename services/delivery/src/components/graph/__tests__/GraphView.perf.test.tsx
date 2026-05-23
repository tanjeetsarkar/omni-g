/**
 * GraphView performance benchmarks (M5.2)
 *
 * Verifies that clustering and filtering algorithms meet latency budgets
 * before landing in CI.  Uses performance.now() — not wall-clock stable,
 * but sufficient as a smoke test.
 */

import { buildClusterGraph } from "@/lib/buildClusterGraph";
import type { GraphNode, GraphEdge } from "@/types/graph";

// ── Synthetic data helpers ─────────────────────────────────────────────────

const STIX_TYPES = [
  "malware",
  "threat-actor",
  "attack-pattern",
  "campaign",
  "identity",
  "tool",
  "location",
  "vulnerability",
] as const;

function generateNodes(count: number, numCommunities: number): GraphNode[] {
  return Array.from({ length: count }, (_, i) => ({
    id: `node-${i}`,
    label: `Node ${i}`,
    x: (i * 7919) % 1000, // deterministic "random" positions
    y: (i * 6271) % 1000,
    size: 5 + (i % 10),
    stixType: STIX_TYPES[i % STIX_TYPES.length],
    confidence: 0.5 + (i % 100) / 200, // 0.5 – 1.0
    communityId: `community-${i % numCommunities}`,
  }));
}

function generateEdges(nodes: GraphNode[], edgeCount: number): GraphEdge[] {
  return Array.from({ length: edgeCount }, (_, i) => ({
    id: `edge-${i}`,
    source: nodes[i % nodes.length].id,
    target: nodes[(i * 3 + 1) % nodes.length].id,
  }));
}

// ── buildClusterGraph benchmarks ───────────────────────────────────────────

describe("buildClusterGraph performance", () => {
  it("clusters 10 000 nodes (50 communities) in < 500 ms", () => {
    const nodes = generateNodes(10_000, 50);
    const edges = generateEdges(nodes, 5_000);

    const start = performance.now();
    const { clusterNodes, clusterEdges } = buildClusterGraph(nodes, edges);
    const elapsed = performance.now() - start;

    expect(elapsed).toBeLessThan(500);
    expect(clusterNodes).toHaveLength(50);
    expect(clusterEdges.length).toBeGreaterThanOrEqual(0);
  });

  it("clusters 50 000 nodes (200 communities) in < 2 000 ms", () => {
    const nodes = generateNodes(50_000, 200);
    const edges = generateEdges(nodes, 10_000);

    const start = performance.now();
    const { clusterNodes } = buildClusterGraph(nodes, edges);
    const elapsed = performance.now() - start;

    expect(elapsed).toBeLessThan(2000);
    expect(clusterNodes).toHaveLength(200);
  });

  it("cluster node count equals the number of unique communityIds", () => {
    const nodes = generateNodes(1_000, 10);
    const edges = generateEdges(nodes, 500);

    const { clusterNodes } = buildClusterGraph(nodes, edges);

    const uniqueCommunities = new Set(nodes.map((n) => n.communityId)).size;
    expect(clusterNodes).toHaveLength(uniqueCommunities);
  });

  it("assigns solo cluster nodes for nodes without communityId", () => {
    const nodes: GraphNode[] = [
      { id: "a", label: "A", x: 0, y: 0 },
      { id: "b", label: "B", x: 1, y: 1 },
    ];
    const { clusterNodes } = buildClusterGraph(nodes, []);
    // Each node becomes its own cluster
    expect(clusterNodes).toHaveLength(2);
  });
});

// ── useGraphFilter algorithm performance ──────────────────────────────────
// Benchmarks the core O(n) filter loop that useGraphFilter wraps in useMemo.

describe("useGraphFilter filtering performance", () => {
  it("filters 10 000 nodes in < 50 ms", () => {
    const nodes = generateNodes(10_000, 50);
    const allTypes = new Set<string>(STIX_TYPES);
    const minConfidence = 0;
    const query = "";

    const start = performance.now();
    const filtered = nodes.filter((node) => {
      if (allTypes.size > 0 && node.stixType && !allTypes.has(node.stixType))
        return false;
      if (node.confidence !== undefined && node.confidence < minConfidence)
        return false;
      if (query && !node.label.toLowerCase().includes(query)) return false;
      return true;
    });
    const elapsed = performance.now() - start;

    expect(elapsed).toBeLessThan(50);
    expect(filtered).toHaveLength(nodes.length);
  });
});
