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
  communityId?: string;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  label?: string;
}
