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
 * B3 + V4 Track 1: Confidence-driven visual encoding on roundRect card nodes.
 * - opacity = 0.4 + (confidence * 0.6) — low-confidence entities visually recede
 * - High-confidence entities (>0.8) get a thicker border
 * - Label only shown for nodes with confidence > 0.3
 * - symbol: 'roundRect', symbolSize: [170, 54] — Figma-style card dimensions
 */
export function transformToEChartsData(
  evidenceNodes: EvidenceNode[],
  edges: EvidenceEdge[],
) {
  const total = evidenceNodes.length;

  const nodes = evidenceNodes.map((node, idx) => {
    const confidence = Math.max(0, Math.min(1, node.score));
    const opacity = 0.4 + confidence * 0.6;
    const isHighConfidence = confidence > 0.8;
    const labelEnabled = confidence > 0.3;

    // Deterministic x/y for static (layout: "none") rendering.  Force and
    // circular layouts override these, so they're harmless in other modes.
    const angle = total > 1 ? (2 * Math.PI * idx) / total : 0;
    const radius = 300;
    const x = Math.cos(angle) * radius;
    const y = Math.sin(angle) * radius;

    return {
      id: node.id,
      name: node.id, // Must use ID as unique identifier 'name' so ECharts links can resolve perfectly
      label: buildRichTextLabel(node), // V4 Track 1: rich-text card label
      symbol: "roundRect",
      symbolSize: [170, 54], // V4 Track 1: Figma-style card dimensions
      category: node.type,
      value: node.score,
      x,
      y,
      itemStyle: {
        color: "#0F172A", // V4 Track 1: dark card background
        opacity,
        borderColor: isHighConfidence ? "#f8fafc" : "#334155",
        borderWidth: isHighConfidence ? 2 : 1.5,
        borderRadius: 8,
      },
      labelEnabled, // controls series-level label visibility
      rawContext: node.raw_text,
      sourceId: node.source_id,
      sourceName: node.source_name,
      sourceUrl: node.source_url,
      pluginName: node.plugin_name,
      subEntityCount: node.sub_entity_count ?? 0,
      timestamp: node.created_at,
      // Confidence field for tooltips
      confidence,
    };
  });

  const nodeIds = new Set(evidenceNodes.map((n) => n.id));

  const links = edges
    .filter(
      (edge) => nodeIds.has(edge.source_id) && nodeIds.has(edge.target_id),
    )
    .map((edge) => ({
      source: edge.source_id,
      target: edge.target_id,
      value: edge.weight,
      lineStyle: {
        width: Math.max(1, edge.weight * 3),
        opacity: 0.7,
        color: "#475569",
      },
    }));

  return { nodes, links };
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
