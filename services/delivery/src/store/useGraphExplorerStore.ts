"use client";

import { create } from "zustand";
import type {
  CustomNodeResponse,
  Entity,
  Relationship,
  ContextUnit,
} from "../types/entities";

/**
 * V4 Track 1: global canvas state for the Figma-style ECharts explorer.
 *
 * The store owns the query, tuning dials (τ / D_max / L_max), the rendered
 * node/edge arrays, and the currently-selected node. `executeQuery` purges
 * stale canvas state before issuing a new /api/query request so the UI never
 * shows a stale graph alongside a fresh query.
 */

export interface CanvasNode extends CustomNodeResponse {
  /** Degree of the node in the returned subgraph (alias of sub_entity_count). */
  depth?: number;
}

export interface CanvasEdge {
  id: string;
  source: string;
  target: string;
  weight: number;
}

interface GraphExplorerState {
  // ── Query + tuning dials ──────────────────────────────────────────────
  query: string;
  depth: number; // D_max ∈ [1, 4]
  relevanceThreshold: number; // τ ∈ [0.1, 1.0]
  tokenCap: number; // L_max ∈ [2048, 8192]
  tenantId: string;

  // ── Canvas state ──────────────────────────────────────────────────────
  nodes: CanvasNode[];
  edges: CanvasEdge[];
  entities: Entity[];
  relationships: Relationship[];
  contextUnits: ContextUnit[];
  selectedNode: CanvasNode | null;
  isLoading: boolean;
  error: string | null;

  // ── Actions ──────────────────────────────────────────────────────────
  setQuery: (query: string) => void;
  setSettings: (depth: number, threshold: number, tokenCap: number) => void;
  setTenantId: (tenantId: string) => void;
  executeQuery: () => Promise<void>;
  selectNode: (nodeId: string | null) => void;
  clearCanvas: () => void;
  /** Merge real-time entity/relationship updates from WebSocket alerts. */
  mergeRealtime: (entities: Entity[], relationships: Relationship[]) => void;
}

const DEFAULT_TENANT =
  (typeof process !== "undefined" && process.env.NEXT_PUBLIC_TENANT_ID) ||
  "default";

export const useGraphExplorerStore = create<GraphExplorerState>((set, get) => ({
  query: "",
  depth: 2,
  relevanceThreshold: 0.0,
  tokenCap: 4096,
  tenantId: DEFAULT_TENANT,

  nodes: [],
  edges: [],
  entities: [],
  relationships: [],
  contextUnits: [],
  selectedNode: null,
  isLoading: false,
  error: null,

  setQuery: (query) => set({ query }),

  setSettings: (depth, threshold, tokenCap) =>
    set({
      depth,
      relevanceThreshold: threshold,
      tokenCap,
    }),

  setTenantId: (tenantId) => set({ tenantId }),

  clearCanvas: () =>
    set({ nodes: [], edges: [], selectedNode: null, error: null }),

  executeQuery: async () => {
    const { query, depth, relevanceThreshold, tenantId } = get();
    const trimmed = query.trim();
    if (!trimmed) return;

    // STEP 1: purge stale canvas state immediately so the user never sees
    // a stale graph alongside a fresh query.
    set({
      nodes: [],
      edges: [],
      entities: [],
      relationships: [],
      contextUnits: [],
      selectedNode: null,
      isLoading: true,
      error: null,
    });

    try {
      const res = await fetch("/api/query", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query: trimmed,
          tenant_id: tenantId,
          limit: 50,
          relevance_threshold: relevanceThreshold,
          traversal_depth: depth,
        }),
      });
      if (!res.ok) {
        const errBody = await res.json().catch(() => ({}));
        throw new Error(
          (errBody as { error?: string }).error ||
            `Query failed (${res.status})`,
        );
      }
      const data = await res.json();

      // STEP 2: render fresh nodes. Prefer the structured `nodes` payload
      // (V4 Track 2) when present; fall back to mapping legacy entities.
      const customNodes: CanvasNode[] = (data.nodes ?? []).map(
        (n: CustomNodeResponse) => ({ ...n, depth: 0 }),
      );
      const entities: Entity[] = data.entities ?? [];
      const relationships: Relationship[] = data.relationships ?? [];
      const contextUnits: ContextUnit[] = data.context_units ?? [];

      let nodes = customNodes;
      const edges: CanvasEdge[] = relationships.map((r) => ({
        id: r.id,
        source: r.source_ref,
        target: r.target_ref,
        weight: r.confidence,
      }));

      if (nodes.length === 0 && entities.length > 0) {
        // Legacy fallback: derive canvas nodes from entities + context units.
        nodes = entities.map((e) => {
          const ctx = contextUnits.find((c) => c.entity_ids?.includes(e.id));
          return {
            id: e.id,
            entity_name: e.name,
            entity_type: e.type,
            sub_entity_count: relationships.filter(
              (r) => r.source_ref === e.id || r.target_ref === e.id,
            ).length,
            confidence_score: e.confidence,
            source: {
              source_name: ctx?.text?.slice(0, 40) || e.source_id || "unknown",
              source_url: null,
              ingested_at: e.created,
              mcp_plugin_name: null,
            },
            raw_context: ctx
              ? {
                  snippet_text: ctx.text,
                  char_offset_start: 0,
                  char_offset_end: ctx.text.length,
                  document_id: ctx.context_id,
                }
              : null,
            depth: 0,
          };
        });
      }

      set({
        nodes,
        edges,
        entities,
        relationships,
        contextUnits,
        isLoading: false,
      });
    } catch (err) {
      set({
        isLoading: false,
        error: err instanceof Error ? err.message : "Query failed",
      });
    }
  },

  selectNode: (nodeId) => {
    if (nodeId === null) {
      set({ selectedNode: null });
      return;
    }
    const node = get().nodes.find((n) => n.id === nodeId) ?? null;
    set({ selectedNode: node });
  },

  mergeRealtime: (entities, relationships) => {
    const existingIds = new Set(get().nodes.map((n) => n.id));
    const newNodes: CanvasNode[] = entities
      .filter((e) => !existingIds.has(e.id))
      .map((e) => ({
        id: e.id,
        entity_name: e.name,
        entity_type: e.type,
        sub_entity_count: 0,
        confidence_score: e.confidence,
        source: {
          source_name: e.source_id || "unknown",
          source_url: null,
          ingested_at: e.created,
          mcp_plugin_name: null,
        },
        raw_context: null,
        depth: 1,
      }));
    const newEdges: CanvasEdge[] = relationships.map((r) => ({
      id: r.id,
      source: r.source_ref,
      target: r.target_ref,
      weight: r.confidence,
    }));
    set((state) => ({
      nodes: [...state.nodes, ...newNodes],
      edges: [...state.edges, ...newEdges],
      entities: [...state.entities, ...entities],
      relationships: [...state.relationships, ...relationships],
    }));
  },
}));
