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

export function transformToEChartsData(
  evidenceNodes: EvidenceNode[],
  edges: EvidenceEdge[],
) {
  const nodes = evidenceNodes.map((node) => ({
    id: node.id,
    name: node.id, // Must use ID as unique identifier 'name' so ECharts links can resolve perfectly
    label: node.label, // Human-readable string loaded into custom field
    symbolSize: node.depth === 0 ? 45 : node.depth === 1 ? 32 : 22,
    category: node.type,
    value: node.score,
    itemStyle: { color: getTypeColor(node.type) },
    rawContext: node.raw_text,
    sourceId: node.source_id,
    timestamp: node.created_at,
  }));

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
