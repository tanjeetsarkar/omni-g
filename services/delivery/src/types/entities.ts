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
  search_id?: string;
  entities: Entity[];
  relationships: Relationship[];
  // V4 Track 2: structured rich-node payload with provenance.
  nodes?: CustomNodeResponse[];
  // V4 Track 2: zero-mem invariant — graph expansion consumes 0 LLM tokens.
  total_tokens_consumed?: number;
  // Phase 5: root entity ID for radial tree layout.
  tree_root_id?: string;
  // V4 Phase 9: BLUF summary object for the BlufStrip component.
  summary?: SearchSummary;
}

/** V4 Phase 9: structured summary emitted by Processor /search. */
export interface SearchSummary {
  total_entities: number;
  total_relationships: number;
  entity_types: Record<string, number>;
  top_entities: { name: string; type: string; degree: number }[];
  sources: string[];
  cached: boolean;
  cache_tier: string | null;
  pipeline_running: boolean;
}

/** V4 Track 2: human-readable source provenance attached to every node. */
export interface NodeProvenance {
  source_name: string;
  source_url: string | null;
  ingested_at: string;
  mcp_plugin_name: string | null;
}

/** V4 Track 2: verbatim source text excerpt with character offsets. */
export interface RawContextSnippet {
  snippet_text: string;
  char_offset_start: number;
  char_offset_end: number;
  document_id: string;
}

/** V4 Track 2: structured node for the ECharts rich-text card renderer. */
export interface CustomNodeResponse {
  id: string;
  entity_name: string;
  entity_type: string;
  sub_entity_count: number;
  confidence_score: number;
  source: NodeProvenance;
  raw_context: RawContextSnippet | null;
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

/** V4 Phase 3: a single history suggestion from fuzzy query matching. */
export interface HistorySuggestion {
  query_text: string;
  search_id: string;
  timestamp: string;
  entity_count: number;
  similarity_score: number;
}

/** V4 Phase 3: response wrapper for /api/query/history. */
export interface HistorySearchResponse {
  suggestions: HistorySuggestion[];
}
