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
 * B3: Confidence-driven visual encoding.
 * - opacity = 0.4 + (confidence * 0.6) — low-confidence entities visually recede
 * - High-confidence entities (>0.8) get a thicker border
 * - Label only shown for nodes with confidence > 0.3
 */
export function transformToEChartsData(
  evidenceNodes: EvidenceNode[],
  edges: EvidenceEdge[],
) {
  const nodes = evidenceNodes.map((node) => {
    const confidence = Math.max(0, Math.min(1, node.score));
    const opacity = 0.4 + confidence * 0.6;
    const isHighConfidence = confidence > 0.8;
    const labelEnabled = confidence > 0.3;

    return {
      id: node.id,
      name: node.id, // Must use ID as unique identifier 'name' so ECharts links can resolve perfectly
      label: node.label, // Human-readable string loaded into custom field
      symbolSize: node.depth === 0 ? 45 : node.depth === 1 ? 32 : 22,
      category: node.type,
      value: node.score,
      itemStyle: {
        color: getTypeColor(node.type),
        opacity,
        borderColor: isHighConfidence ? "#f8fafc" : getTypeColor(node.type),
        borderWidth: isHighConfidence ? 2 : 0,
      },
      labelEnabled, // controls series-level label visibility
      rawContext: node.raw_text,
      sourceId: node.source_id,
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
      lineStyle: { width: Math.max(1, edge.weight * 3), opacity: 0.6 },
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
