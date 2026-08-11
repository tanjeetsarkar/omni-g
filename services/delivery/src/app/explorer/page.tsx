"use client";

import React, { useState, useEffect, useCallback, Suspense } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import {
  Search,
  Loader,
  Hexagon,
  ShieldAlert,
  Layers,
  TrendingUp,
  Clock,
} from "lucide-react";
import {
  EChartsGraphCanvas,
  EChartsNode,
} from "../../components/canvas/EChartsGraphCanvas";
import { SourceTraceDrawer } from "../../components/drawer/SourceTraceDrawer";
import { FloatingSearchBar } from "../../components/controls/FloatingSearchBar";
import { SettingsGearPanel } from "../../components/controls/SettingsGearPanel";
import { useGraphExplorerStore } from "../../store/useGraphExplorerStore";
import {
  transformToEChartsData,
  EvidenceNode,
  EvidenceEdge,
} from "../../components/canvas/useEChartsGraphAdapter";
import type {
  Entity,
  Relationship,
  SearchResponse,
  ContextUnit,
  TrendingEntity,
  CustomNodeResponse,
} from "../../types/entities";
import { getSocket, joinTenant } from "../../lib/socket";
import { usePipelineEvents } from "../../hooks/usePipelineEvents";
import { useRealtimeNodes } from "../../hooks/useRealtimeNodes";
import { useSearchHistory } from "../../hooks/useSearchHistory";
import PipelineProgressToast, {
  ToastState,
} from "../../components/graph/PipelineProgressToast";
import ActivityDrawer from "../../components/graph/ActivityDrawer";
import { BlufStrip } from "../../components/synthesis/BlufStrip";
import { NotificationBell } from "../../components/notifications/NotificationBell";

export function ExplorerContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const initialQuery = searchParams.get("q") ?? "";

  const tenantId = process.env.NEXT_PUBLIC_TENANT_ID ?? "default";

  // V4 Track 1: canvas state lives in the Zustand store (single source of
  // truth for nodes/edges/selectedNode). The page retains UI-only state
  // (search input, toast, trending, history) that the store does not own.
  const storeNodes = useGraphExplorerStore((s) => s.nodes);
  const storeEdges = useGraphExplorerStore((s) => s.edges);
  const storeClearCanvas = useGraphExplorerStore((s) => s.clearCanvas);
  const storeMergeRealtime = useGraphExplorerStore((s) => s.mergeRealtime);
  const storeSelectNode = useGraphExplorerStore((s) => s.selectNode);
  const storeSetTenantId = useGraphExplorerStore((s) => s.setTenantId);
  const storeDepth = useGraphExplorerStore((s) => s.depth);
  const storeThreshold = useGraphExplorerStore((s) => s.relevanceThreshold);

  // Derive EvidenceNode/EvidenceEdge arrays from the store for the adapter.
  const evidenceNodes: EvidenceNode[] = storeNodes.map((n) => ({
    id: n.id,
    label: n.entity_name,
    type: n.entity_type,
    score: n.confidence_score,
    depth: n.depth ?? 0,
    raw_text: n.raw_context?.snippet_text,
    source_id: n.source.source_url ?? undefined,
    created_at: n.source.ingested_at,
    source_name: n.source.source_name,
    source_url: n.source.source_url ?? undefined,
    plugin_name: n.source.mcp_plugin_name ?? undefined,
    sub_entity_count: n.sub_entity_count,
  }));
  const evidenceEdges: EvidenceEdge[] = storeEdges.map((e) => ({
    id: e.id,
    source_id: e.source,
    target_id: e.target,
    weight: e.weight,
  }));

  const [searchQuery, setSearchQuery] = useState(initialQuery);
  const [submitting, setSubmitting] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);

  // Context units for BLUF strip (kept local — store owns nodes/edges only)
  const [contextUnits, setContextUnits] = useState<ContextUnit[]>([]);

  // Trending entities for empty state (B8)
  const [trendingEntities, setTrendingEntities] = useState<TrendingEntity[]>(
    [],
  );
  const [trendingLoading, setTrendingLoading] = useState(false);

  // Ingestion progress toast states
  const [toastState, setToastState] = useState<ToastState>("idle");
  const [errorDetail, setErrorDetail] = useState<string | null>(null);
  const [currentSearchQuery, setCurrentSearchQuery] = useState(initialQuery);

  const socket = getSocket();
  const { stageStatuses } = usePipelineEvents(socket);

  const { newEntities, newRelationships, clearNewEntities } = useRealtimeNodes({
    tenantId,
    enabled: true,
  });

  // Search history (B4)
  const { history, addSearch } = useSearchHistory();

  // Sync tenant id into the store so floating controls dispatch queries
  // with the correct tenant scope.
  useEffect(() => {
    storeSetTenantId(tenantId);
  }, [tenantId, storeSetTenantId]);

  // Join the Socket.io tenant room on mount
  useEffect(() => {
    joinTenant(tenantId);
  }, [tenantId]);

  // Synchronize toastState when pipeline completes.  We watch both
  // alert_publishing (highest-confidence pipelines) and the pipeline_complete
  // synthetic stage that the processor always emits regardless of confidence.
  useEffect(() => {
    if (toastState !== "running") return;
    if (
      stageStatuses.alert_publishing === "done" ||
      stageStatuses.pipeline_complete === "done"
    ) {
      setToastState("done");
    }
  }, [
    toastState,
    stageStatuses.alert_publishing,
    stageStatuses.pipeline_complete,
  ]);

  // 90-second safety fallback timeout for the running toast
  useEffect(() => {
    if (toastState !== "running") return;
    const timer = setTimeout(() => {
      setToastState("done");
    }, 90000); // 90 seconds
    return () => clearTimeout(timer);
  }, [toastState]);

  // Fetch trending entities on mount (B8)
  useEffect(() => {
    async function fetchTrending() {
      setTrendingLoading(true);
      try {
        const res = await fetch(
          `/api/trending?tenant_id=${encodeURIComponent(tenantId)}&limit=5`,
        );
        if (res.ok) {
          const data = await res.json();
          setTrendingEntities(data.entities ?? []);
        }
      } catch {
        // Trending unavailable — silently ignore
      } finally {
        setTrendingLoading(false);
      }
    }
    fetchTrending();
  }, [tenantId]);

  // Merge real-time entities and relationships when alerts are broadcasted
  useEffect(() => {
    if (newEntities.length > 0 || newRelationships.length > 0) {
      // V4 Track 1: merge realtime updates into the Zustand store.
      storeMergeRealtime(newEntities, newRelationships);
      clearNewEntities();
    }
  }, [newEntities, newRelationships, storeMergeRealtime, clearNewEntities]);

  const runSearch = useCallback(
    async (q: string) => {
      const trimmed = q.trim();
      if (!trimmed) return;
      setSubmitting(true);
      setSearchError(null);
      setErrorDetail(null);
      setCurrentSearchQuery(trimmed);

      // V4 Track 1: purge stale canvas state via the store before fetching.
      storeClearCanvas();

      try {
        const res = await fetch("/api/query", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            query: trimmed,
            tenant_id: tenantId,
            limit: 50,
            relevance_threshold: storeThreshold,
            traversal_depth: storeDepth,
          }),
        });

        if (!res.ok) {
          const err: { error?: string } = await res.json().catch(() => ({}));
          const errMsg = err.error ?? `Graph query failed: HTTP ${res.status}`;
          setSearchError(errMsg);
          setErrorDetail(errMsg);
          setToastState("error");
          return;
        }

        const data: SearchResponse & { context_units?: ContextUnit[] } =
          await res.json();
        const ctxUnits = data.context_units || [];

        // V4 Track 1: write results into the Zustand store. Prefer the
        // structured `nodes` payload; fall back to mapping legacy entities.
        const customNodes = (data.nodes ?? []).map((n: CustomNodeResponse) => ({
          ...n,
          depth: 0,
        }));
        const relationships = data.relationships || [];
        const entities = data.entities || [];

        let nodes = customNodes;
        if (nodes.length === 0 && entities.length > 0) {
          nodes = entities.map((e) => {
            const ctx = ctxUnits.find((c) => c.entity_ids?.includes(e.id));
            return {
              id: e.id,
              entity_name: e.name,
              entity_type: e.type,
              sub_entity_count: relationships.filter(
                (r) => r.source_ref === e.id || r.target_ref === e.id,
              ).length,
              confidence_score: e.confidence,
              source: {
                source_name:
                  ctx?.text?.slice(0, 40) || e.source_id || "unknown",
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
        const edges = relationships.map((r) => ({
          id: r.id,
          source: r.source_ref,
          target: r.target_ref,
          weight: r.confidence,
        }));

        useGraphExplorerStore.setState({
          nodes,
          edges,
          entities,
          relationships,
          contextUnits: ctxUnits,
          selectedNode: null,
        });
        setContextUnits(ctxUnits);

        // ── B4: Add to search history ──
        addSearch(trimmed, nodes.length);

        // Transition layout/toast to running state
        setToastState("running");

        // ── Active Tasked Synthesis: Trigger background on-demand ingestion ────────────────
        // Sends search request to Aggregator to query remote MCP plugins and generate raw Kafka events.
        const searchRes = await fetch("/api/search", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ query: trimmed, sources: [] }),
        });

        if (!searchRes.ok) {
          const searchErr = await searchRes.json().catch(() => ({}));
          const errMsg =
            searchErr.error ??
            `Background search failed: HTTP ${searchRes.status}`;
          setErrorDetail(errMsg);
          setToastState("error");
        }
      } catch (err) {
        const errMsg =
          err instanceof Error ? err.message : "Graph query failed";
        setSearchError(errMsg);
        setErrorDetail(errMsg);
        setToastState("error");
      } finally {
        setSubmitting(false);
      }
    },
    [tenantId, storeThreshold, storeDepth, storeClearCanvas, addSearch],
  );

  const handleRefreshGraph = useCallback(() => {
    runSearch(currentSearchQuery);
    setToastState("idle");
  }, [runSearch, currentSearchQuery]);

  const handleDismissToast = useCallback(() => {
    setToastState("idle");
  }, []);

  const handleRetrySearch = useCallback(() => {
    runSearch(currentSearchQuery);
  }, [runSearch, currentSearchQuery]);

  // Trigger search on init if query is present
  useEffect(() => {
    if (initialQuery) {
      runSearch(initialQuery);
    }
  }, [initialQuery, runSearch]);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!searchQuery.trim()) return;
    router.replace(`/explorer?q=${encodeURIComponent(searchQuery)}`);
    runSearch(searchQuery);
  };

  // Node Selection callback — V4 Track 1: selection lives in the Zustand store.
  const handleNodeSelect = (node: EChartsNode) => {
    storeSelectNode(node.id);
    // If the store has no matching node (legacy ECharts node not in store),
    // seed the store's selectedNode directly from the ECharts payload.
    const nodeExtra = node as unknown as Record<string, unknown>;
    const store = useGraphExplorerStore.getState();
    if (node.id && !store.nodes.some((n) => n.id === node.id)) {
      useGraphExplorerStore.setState((s) => ({
        ...s,
        selectedNode: {
          id: node.id,
          entity_name: node.label ?? node.name,
          entity_type: node.category ?? "Unknown",
          sub_entity_count:
            (nodeExtra.subEntityCount as number | undefined) ?? 0,
          confidence_score: node.value ?? node.confidence ?? 0.5,
          source: {
            source_name:
              (nodeExtra.sourceName as string | undefined) ??
              node.sourceId ??
              "unknown",
            source_url: (nodeExtra.sourceUrl as string | undefined) ?? null,
            ingested_at: node.timestamp ?? "",
            mcp_plugin_name:
              (nodeExtra.pluginName as string | undefined) ?? null,
          },
          raw_context: node.rawContext
            ? {
                snippet_text: node.rawContext,
                char_offset_start: 0,
                char_offset_end: node.rawContext.length,
                document_id: node.sourceId ?? "",
              }
            : null,
        },
      }));
    }
  };

  // Double Click / Drill down dynamic expansion callback
  const handleNodeDrillDown = async (nodeId: string) => {
    const existingNode = evidenceNodes.find((n) => n.id === nodeId);
    const nextDepth = (existingNode?.depth ?? 0) + 1;

    try {
      const res = await fetch("/api/query/expand", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          anchor_node_id: nodeId,
          current_depth: existingNode?.depth ?? 1,
          target_depth: nextDepth,
          tenant_id: tenantId,
        }),
      });

      if (!res.ok) {
        console.error("Expansion failed");
        return;
      }

      const data: SearchResponse & { context_units?: ContextUnit[] } =
        await res.json();
      const ctxUnits = data.context_units || [];

      // V4 Track 1: merge drilldown results into the Zustand store.
      const newNodes = (data.nodes ?? []).map((n: CustomNodeResponse) => ({
        ...n,
        depth: nextDepth,
      }));
      const newEdges = (data.relationships || []).map((r) => ({
        id: r.id,
        source: r.source_ref,
        target: r.target_ref,
        weight: r.confidence,
      }));

      // Merge context units (local — store owns nodes/edges only)
      setContextUnits((prev) => {
        const existingIds = new Set(prev.map((c) => c.context_id));
        const newCtx = ctxUnits.filter((c) => !existingIds.has(c.context_id));
        return [...prev, ...newCtx];
      });

      // Deduplicate merge into the store
      const store = useGraphExplorerStore.getState();
      const existingNodeIds = new Set(store.nodes.map((n) => n.id));
      const existingEdgeIds = new Set(store.edges.map((e) => e.id));
      const nodesToAdd = newNodes.filter((n) => !existingNodeIds.has(n.id));
      const edgesToAdd = newEdges.filter((e) => !existingEdgeIds.has(e.id));
      if (nodesToAdd.length > 0 || edgesToAdd.length > 0) {
        useGraphExplorerStore.setState((s) => ({
          nodes: [...s.nodes, ...nodesToAdd],
          edges: [...s.edges, ...edgesToAdd],
        }));
      }
    } catch (err) {
      console.error("Error expanding node:", err);
    }
  };

  const { nodes, links } = transformToEChartsData(evidenceNodes, evidenceEdges);

  const hasResults = nodes.length > 0;

  return (
    <div className="flex flex-col h-screen bg-slate-950 text-slate-100 overflow-hidden">
      {/* Header */}
      <header className="flex items-center gap-3 px-4 py-2.5 bg-slate-900 border-b border-slate-800/80 shrink-0 select-none">
        <div
          className="flex items-center gap-2 cursor-pointer"
          onClick={() => router.push("/")}
        >
          <Hexagon
            size={18}
            className="text-indigo-500 fill-indigo-500/20 animate-pulse"
          />
          <span className="font-bold text-base tracking-tight">Omni-G</span>
          <span className="text-[10px] text-slate-500 uppercase tracking-widest hidden sm:block">
            Zero-Mem Explorer
          </span>
        </div>

        <div className="w-px h-5 bg-slate-800 shrink-0" />

        <form
          onSubmit={handleSearchSubmit}
          className="flex items-center gap-1.5 flex-1 min-w-0"
          aria-label="Search zero-mem graph"
        >
          <div className="relative flex-1 min-w-0 max-w-lg">
            <Search
              size={13}
              className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-500 pointer-events-none"
            />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Query general intelligence topics directly..."
              className="w-full bg-slate-950 border border-slate-800 text-slate-200 text-xs
                         placeholder-slate-500 rounded-lg pl-7 pr-3 py-1.5
                         focus:outline-none focus:border-indigo-500/80 focus:ring-1 focus:ring-indigo-500/20"
              disabled={submitting}
              autoFocus
            />
          </div>
          <button
            type="submit"
            disabled={!searchQuery.trim() || submitting}
            className="flex items-center justify-center bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-800 disabled:text-slate-600 transition-colors text-white font-medium text-xs rounded-lg px-3 py-1.5"
          >
            {submitting ? (
              <Loader size={12} className="animate-spin text-slate-400" />
            ) : (
              "Explore"
            )}
          </button>
        </form>

        {/* ── B7: Notification bell ── */}
        <NotificationBell />
      </header>

      {/* ── B1: BLUF / Synthesis Strip (only when results exist) ── */}
      {hasResults && contextUnits.length > 0 && (
        <BlufStrip
          contextUnits={contextUnits}
          query={currentSearchQuery}
          tenantId={tenantId}
        />
      )}

      {/* Main Exploration Canvas */}
      <div className="flex-1 relative flex overflow-hidden">
        {searchError && (
          <div className="absolute top-4 left-1/2 -translate-x-1/2 bg-red-950/40 border border-red-900/60 rounded-lg px-4 py-2 text-xs text-red-200 flex items-center gap-2 z-10">
            <ShieldAlert size={14} className="text-red-400" />
            <span>{searchError}</span>
          </div>
        )}

        {!hasResults && !submitting ? (
          <div className="flex-1 flex flex-col items-center justify-center p-8 bg-slate-950 text-center space-y-3 z-0">
            <Layers size={36} className="text-slate-700 animate-bounce" />
            <h2 className="text-slate-300 font-semibold text-sm">
              Enter a search query to explore the localized context graph
            </h2>
            <p className="text-slate-500 text-xs max-w-sm leading-relaxed">
              Our Zero-Mem Dual-View Retrieval engine uses non-generative
              localized walks to quickly discover relationships and evidence
              context units.
            </p>

            {/* ── B4: Recent search history ── */}
            {history.length > 0 && (
              <div className="mt-4 w-full max-w-sm">
                <div className="flex items-center gap-1.5 mb-2">
                  <Clock size={12} className="text-slate-500" />
                  <span className="text-[10px] text-slate-500 uppercase tracking-wider font-semibold">
                    Recent Searches
                  </span>
                </div>
                <div className="flex flex-wrap gap-1.5 justify-center">
                  {history.map((entry) => (
                    <button
                      key={`${entry.query}-${entry.timestamp}`}
                      onClick={() => {
                        setSearchQuery(entry.query);
                        router.replace(
                          `/explorer?q=${encodeURIComponent(entry.query)}`,
                        );
                        runSearch(entry.query);
                      }}
                      className="text-xs px-2.5 py-1 rounded-full bg-slate-800 hover:bg-indigo-900/40 hover:text-indigo-300 text-slate-400 border border-slate-700 transition-colors"
                    >
                      {entry.query}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* ── B8: Trending/recent entities ── */}
            {trendingEntities.length > 0 && (
              <div className="mt-4 w-full max-w-sm">
                <div className="flex items-center gap-1.5 mb-2 justify-center">
                  <TrendingUp size={12} className="text-slate-500" />
                  <span className="text-[10px] text-slate-500 uppercase tracking-wider font-semibold">
                    Recently Added
                  </span>
                </div>
                <div className="flex flex-wrap gap-1.5 justify-center">
                  {trendingEntities.map((entity) => (
                    <button
                      key={entity.id}
                      onClick={() => {
                        setSearchQuery(entity.name);
                        router.replace(
                          `/explorer?q=${encodeURIComponent(entity.name)}`,
                        );
                        runSearch(entity.name);
                      }}
                      className="text-xs px-2.5 py-1 rounded-full bg-slate-800 hover:bg-indigo-900/40 hover:text-indigo-300 text-slate-400 border border-slate-700 transition-colors"
                    >
                      {entity.name}
                      <span className="ml-1 text-[10px] text-slate-600">
                        ({entity.type})
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {trendingLoading && (
              <div className="flex items-center gap-2 mt-2">
                <Loader size={12} className="animate-spin text-slate-500" />
                <span className="text-[10px] text-slate-500">
                  Loading trending entities…
                </span>
              </div>
            )}
          </div>
        ) : (
          <div className="flex-1 h-full w-full relative">
            {/* V4 Track 1: floating Figma-style controls */}
            <FloatingSearchBar />
            <SettingsGearPanel />
            <EChartsGraphCanvas
              nodes={nodes}
              links={links}
              onNodeSelect={handleNodeSelect}
              onNodeDrillDown={handleNodeDrillDown}
            />
          </div>
        )}

        {/* V4 Track 1: responsive evidence drawer (desktop side panel / mobile bottom sheet) */}
        <SourceTraceDrawer />

        {/* Floating live ingestion progress toast (M6 UX) */}
        <PipelineProgressToast
          query={currentSearchQuery}
          toastState={toastState}
          errorDetail={errorDetail}
          socket={socket}
          onRefreshGraph={handleRefreshGraph}
          onDismiss={handleDismissToast}
          onRetry={handleRetrySearch}
        />

        {/* Always-visible pipeline activity drawer */}
        <ActivityDrawer socket={socket} />
      </div>
    </div>
  );
}

export default function ExplorerPage() {
  return (
    <Suspense
      fallback={
        <div className="flex-1 flex items-center justify-center bg-slate-950 text-slate-400">
          <Loader size={24} className="animate-spin" />
        </div>
      }
    >
      <ExplorerContent />
    </Suspense>
  );
}
