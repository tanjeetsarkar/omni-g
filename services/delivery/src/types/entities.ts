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
