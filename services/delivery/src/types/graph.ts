/**
 * Shared graph types for Omni-G Delivery (M5.2)
 */

export interface GraphNode {
  id: string;
  label: string;
  x: number;
  y: number;
  size?: number;
  color?: string;
  stixType?: string;
  confidence?: number;
  communitySummary?: string;
  communityId?: number;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  label?: string;
  /** Confidence score [0.0–1.0] from the resolved relationship — drives SVG path colour in ConceptFlowView */
  confidence?: number;
}
