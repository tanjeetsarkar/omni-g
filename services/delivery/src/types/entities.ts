export interface Entity {
  id: string;
  type: string;
  name: string;
  description: string | null;
  properties: Record<string, unknown>;
  confidence: number;
  tenant_id: string;
  source_id: string | null;
  created: string;
  modified: string;
}

export interface Relationship {
  id: string;
  type: string;
  source_ref: string;
  target_ref: string;
  confidence: number;
  tenant_id: string;
  created: string;
  modified: string;
}

export interface SearchResponse {
  entities: Entity[];
  relationships: Relationship[];
}

export interface CollectionGap {
  gap_id: string;
  description: string;
  priority?: "high" | "medium" | "low";
  status?: string;
  created?: string;
}

export interface Assessment {
  assessment_id: string;
  kiq_id?: string;
  summary: string;
  confidence: number;
  supporting_evidence_ids: string[];
  contradicting_evidence_ids: string[];
  collection_gaps: CollectionGap[];
  recommended_next_actions: string[];
  created: string;
  tenant_id: string;
}

export interface ContextUnit {
  context_id: string;
  score: number;
  text: string;
  entity_ids: string[];
}

export interface TrendingEntity {
  id: string;
  name: string;
  type: string;
  confidence: number;
  created: string;
}

export interface BriefingTranscript {
  id: string;
  text: string;
  entities: string[];
  date: string;
}
