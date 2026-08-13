"use client";

export interface EvidenceNode {
  id: string;
  label: string;
  type: string;
  score: number;
  depth: number;
  raw_text?: string;
  source_id?: string;
  created_at?: string;
  // V4 Track 1: provenance + sub-entity count for rich-text card rendering.
  source_name?: string;
  source_url?: string;
  plugin_name?: string;
  sub_entity_count?: number;
}

export interface EvidenceEdge {
  id: string;
  source_id: string;
  target_id: string;
  weight: number;
}

const TYPE_COLORS: Record<string, string> = {
  FACILITY: "#ef4444",
  PERSON: "#3b82f6",
  STUDY: "#10b981",
  CONCEPT: "#eab308",
  DATE: "#a855f7",
  PERCENT: "#06b6d4",
  LOC: "#14b8a6",
  GPE: "#f43f5e",
  ORGANIZATION: "#f97316",
  ORG: "#f97316",
  MONEY: "#22c55e",
  PRODUCT: "#3b82f6",
  CARDINAL: "#cbd5e1",
};

export function getTypeColor(type: string): string {
  return TYPE_COLORS[type?.toUpperCase()] ?? "#6366f1";
}

/**
 * V4 Track 1: rich-text label formatter for roundRect card nodes.
 *
 * Produces a three-line label:
 *   {typeBadge| TYPE }      — colored type pill
 *   {title| Entity Name}    — bold white title
 *   {subText| +N links 📍 source} — link count + source tag
 *
 * The `rich` style object is returned separately and merged into the series
 * label config by the canvas component.
 */
export function buildRichTextLabel(node: EvidenceNode): string {
  const linkCount = node.sub_entity_count ?? 0;
  const sourceTag = node.source_name ? ` 📍 ${node.source_name}` : "";
  return [
    `{typeBadge| ${node.type} }`,
    `{title| ${node.label} }`,
    `{subText| +${linkCount} links${sourceTag} }`,
  ].join("\n");
}

export const RICH_LABEL_STYLES = {
  typeBadge: {
    backgroundColor: "#2563EB",
    color: "#FFF",
    borderRadius: 3,
    padding: [2, 4],
    fontSize: 9,
  },
  title: {
    color: "#F8FAFC",
    fontSize: 12,
    fontWeight: "bold" as const,
    padding: [3, 0],
  },
  subText: {
    color: "#94A3B8",
    fontSize: 9,
  },
  source: {
    color: "#38BDF8",
    fontSize: 9,
  },
};

/**
 * Phase 5: transform evidence nodes + edges into a query-rooted radial tree
 * suitable for ECharts `series.type: "tree"` with `layout: "radial"`.
 *
 * Algorithm:
 *  1. Find the root node — highest degree (most incident edges). Tie-break on
 *     highest confidence/score.
 *  2. Build an adjacency map from edges.
 *  3. BFS from root to assign depth levels.
 *  4. Assign radial coordinates (concentric rings) for custom x/y positioning.
 *  5. Build a recursive ECharts tree `{ name, children: [...] }` structure.
 *  6. Return `{ treeData, nodes, links }` where nodes carry computed x/y.
 */
export function transformToRadialTreeData(
  evidenceNodes: EvidenceNode[],
  edges: EvidenceEdge[],
) {
  const nodeMap = new Map<string, EvidenceNode>();
  for (const n of evidenceNodes) {
    nodeMap.set(n.id, n);
  }

  // ── Step 1: Find root ─────────────────────────────────────────────────
  // Degree counting: each edge contributes 1 to both source and target.
  const degree = new Map<string, number>();
  for (const e of edges) {
    degree.set(e.source_id, (degree.get(e.source_id) ?? 0) + 1);
    degree.set(e.target_id, (degree.get(e.target_id) ?? 0) + 1);
  }

  let rootId = evidenceNodes[0]?.id ?? "";
  let bestDegree = -1;
  let bestConf = -1;
  for (const n of evidenceNodes) {
    const d = degree.get(n.id) ?? 0;
    const c = n.score;
    if (d > bestDegree || (d === bestDegree && c > bestConf)) {
      bestDegree = d;
      bestConf = c;
      rootId = n.id;
    }
  }

  if (!rootId) {
    return { treeData: null, nodes: [], links: [] };
  }

  // ── Step 2: Build adjacency map ────────────────────────────────────────
  const adjacency = new Map<string, { neighbor: string; weight: number }[]>();
  for (const e of edges) {
    if (!adjacency.has(e.source_id)) adjacency.set(e.source_id, []);
    if (!adjacency.has(e.target_id)) adjacency.set(e.target_id, []);
    adjacency
      .get(e.source_id)!
      .push({ neighbor: e.target_id, weight: e.weight });
    adjacency
      .get(e.target_id)!
      .push({ neighbor: e.source_id, weight: e.weight });
  }

  // ── Step 3: BFS to assign depth ───────────────────────────────────────
  const depthMap = new Map<string, number>();
  const visited = new Set<string>();
  const queue: string[] = [rootId];
  depthMap.set(rootId, 0);
  visited.add(rootId);

  while (queue.length > 0) {
    const current = queue.shift()!;
    const currentDepth = depthMap.get(current)!;
    for (const { neighbor } of adjacency.get(current) ?? []) {
      if (!visited.has(neighbor)) {
        visited.add(neighbor);
        depthMap.set(neighbor, currentDepth + 1);
        queue.push(neighbor);
      }
    }
  }

  // ── Step 4: Assign radial coordinates ─────────────────────────────────
  const depthBuckets = new Map<number, string[]>();
  for (const [id, d] of depthMap) {
    if (!depthBuckets.has(d)) depthBuckets.set(d, []);
    depthBuckets.get(d)!.push(id);
  }

  const RING_BASE = 100;
  const RING_STEP = 150;
  const coordMap = new Map<string, { x: number; y: number }>();

  for (const [depth, nodeIds] of depthBuckets) {
    const radius = RING_BASE + depth * RING_STEP;
    const count = nodeIds.length;
    nodeIds.forEach((id, idx) => {
      const angle = count > 0 ? (2 * Math.PI * idx) / count : 0;
      coordMap.set(id, {
        x: Math.cos(angle) * radius,
        y: Math.sin(angle) * radius,
      });
    });
  }

  // ── Step 5: Build recursive tree data for ECharts ──────────────────────
  function buildTreeNode(
    nodeId: string,
    parentId: string | null,
  ): Record<string, unknown> {
    const node = nodeMap.get(nodeId);
    if (!node) return { name: nodeId, children: [] };

    const confidence = Math.max(0, Math.min(1, node.score));
    const coord = coordMap.get(nodeId);

    const childIds =
      adjacency
        .get(nodeId)
        ?.map((a) => a.neighbor)
        .filter((id) => id !== parentId) ?? [];

    const typeColor = getTypeColor(node.type);

    return {
      name: node.id,
      label: buildRichTextLabel(node),
      value: node.sub_entity_count ?? degree.get(nodeId) ?? 1,
      itemStyle: {
        color: typeColor,
        borderColor: confidence > 0.8 ? "#f8fafc" : "#334155",
        borderWidth: confidence > 0.8 ? 2 : 1.5,
        borderRadius: 8,
        opacity: 0.4 + confidence * 0.6,
      },
      category: node.type,
      confidence,
      rawContext: node.raw_text,
      sourceId: node.source_id,
      sourceName: node.source_name,
      sourceUrl: node.source_url,
      pluginName: node.plugin_name,
      subEntityCount: node.sub_entity_count ?? 0,
      timestamp: node.created_at,
      x: coord?.x,
      y: coord?.y,
      collapsed:
        depthMap.get(nodeId) !== undefined && depthMap.get(nodeId)! >= 3,
      children: childIds.map((cid) => buildTreeNode(cid, nodeId)),
    };
  }

  const treeData = buildTreeNode(rootId, null);

  // ── Step 6: Generate nodes and links ───────────────────────────────────
  const nodes: Array<Record<string, unknown>> = [];
  const links: Array<Record<string, unknown>> = [];

  function collectNodesAndLinks(
    treeNode: Record<string, unknown>,
    parentId: string | null,
  ) {
    const nodeId = treeNode.name as string;
    const coord = coordMap.get(nodeId);
    const n = nodeMap.get(nodeId);
    const confidence = (treeNode.confidence as number) ?? n?.score ?? 0.5;

    nodes.push({
      id: nodeId,
      name: nodeId,
      label: treeNode.label as string,
      symbol: "circle",
      symbolSize: Math.max(
        8,
        Math.min(40, ((treeNode.value as number) ?? 1) * 5 + 8),
      ),
      category: (treeNode.category as string) ?? "Unknown",
      value: treeNode.value as number,
      x: coord?.x ?? 0,
      y: coord?.y ?? 0,
      itemStyle: treeNode.itemStyle as Record<string, unknown>,
      confidence,
      rawContext: treeNode.rawContext as string | undefined,
      sourceId: treeNode.sourceId as string | undefined,
      sourceName: treeNode.sourceName as string | undefined,
      sourceUrl: treeNode.sourceUrl as string | undefined,
      pluginName: treeNode.pluginName as string | undefined,
      subEntityCount: treeNode.subEntityCount as number | undefined,
      timestamp: treeNode.timestamp as string | undefined,
    });

    if (parentId) {
      const edgeWeight =
        edges.find(
          (e) =>
            (e.source_id === parentId && e.target_id === nodeId) ||
            (e.source_id === nodeId && e.target_id === parentId),
        )?.weight ?? 0.5;

      links.push({
        source: parentId,
        target: nodeId,
        value: edgeWeight,
        lineStyle: {
          width: Math.max(1, edgeWeight * 3),
          opacity: 0.6,
        },
      });
    }

    const children = treeNode.children as Record<string, unknown>[] | undefined;
    if (children) {
      for (const child of children) {
        collectNodesAndLinks(child, nodeId);
      }
    }
  }

  collectNodesAndLinks(treeData, null);

  return { treeData, nodes, links };
}

/**
 * Helper: format confidence as a visual bar for tooltips.
 */
export function formatConfidenceBar(score: number): string {
  const clamped = Math.max(0, Math.min(1, score));
  const filled = Math.round(clamped * 10);
  const empty = 10 - filled;
  return "█".repeat(filled) + "░".repeat(empty);
}
