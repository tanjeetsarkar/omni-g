/**
 * buildClusterGraph — collapses individual nodes into community-level clusters.
 *
 * Used by semantic zoom: when the camera is zoomed far out, individual nodes
 * are replaced by one cluster node per communityId.
 */

import type { GraphNode, GraphEdge } from "@/types/graph";

const STIX_COLORS: Record<string, string> = {
  "threat-actor": "#ef4444",
  malware: "#f97316",
  "attack-pattern": "#eab308",
  campaign: "#a855f7",
  identity: "#3b82f6",
  tool: "#06b6d4",
  location: "#10b981",
  vulnerability: "#f43f5e",
};

export function buildClusterGraph(
  nodes: GraphNode[],
  edges: GraphEdge[],
): { clusterNodes: GraphNode[]; clusterEdges: GraphEdge[] } {
  // ── Group nodes by communityId ─────────────────────────────────────────────
  const communities = new Map<string, GraphNode[]>();

  for (const node of nodes) {
    const cid = node.communityId ?? `__solo__${node.id}`;
    const group = communities.get(cid);
    if (group) {
      group.push(node);
    } else {
      communities.set(cid, [node]);
    }
  }

  // ── Build one cluster node per community ───────────────────────────────────
  const clusterNodes: GraphNode[] = [];
  const nodeToCluster = new Map<string, string>(); // nodeId → clusterNodeId

  communities.forEach((members, cid) => {
    // Centroid position
    let sumX = 0;
    let sumY = 0;
    let totalSize = 0;
    const typeCounts = new Map<string, number>();

    for (const n of members) {
      sumX += n.x;
      sumY += n.y;
      totalSize += n.size ?? 5;
      if (n.stixType) {
        typeCounts.set(n.stixType, (typeCounts.get(n.stixType) ?? 0) + 1);
      }
    }

    // Most common stixType
    let dominantType: string | undefined;
    let maxCount = 0;
    typeCounts.forEach((count, type) => {
      if (count > maxCount) {
        maxCount = count;
        dominantType = type;
      }
    });

    const clusterNodeId = `cluster__${cid}`;

    clusterNodes.push({
      id: clusterNodeId,
      label: `${dominantType ?? cid} (${members.length})`,
      x: sumX / members.length,
      y: sumY / members.length,
      size: totalSize,
      color: STIX_COLORS[dominantType ?? ""] ?? "#6366f1",
      stixType: dominantType,
      communityId: cid,
      communitySummary: members[0]?.communitySummary,
    });

    for (const n of members) {
      nodeToCluster.set(n.id, clusterNodeId);
    }
  });

  // ── Build deduplicated cluster-level edges ─────────────────────────────────
  const clusterEdges: GraphEdge[] = [];
  const seen = new Set<string>();

  edges.forEach((edge, i) => {
    const src = nodeToCluster.get(edge.source);
    const tgt = nodeToCluster.get(edge.target);
    if (!src || !tgt || src === tgt) return;

    // Canonical key (order-independent dedup)
    const key = src < tgt ? `${src}|${tgt}` : `${tgt}|${src}`;
    if (!seen.has(key)) {
      seen.add(key);
      clusterEdges.push({
        id: `ce-${i}`,
        source: src,
        target: tgt,
        label: edge.label,
      });
    }
  });

  return { clusterNodes, clusterEdges };
}
