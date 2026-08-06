"use client";

import React, {
  useState,
  useEffect,
  useCallback,
  useRef,
  Suspense,
} from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { Search, Loader, Hexagon, ShieldAlert, Layers } from "lucide-react";
import {
  EChartsGraphCanvas,
  EChartsNode,
} from "../../components/canvas/EChartsGraphCanvas";
import { SourceTracePane } from "../../components/inspector/SourceTracePane";
import {
  transformToEChartsData,
  EvidenceNode,
  EvidenceEdge,
} from "../../components/canvas/useEChartsGraphAdapter";
import type {
  Entity,
  Relationship,
  SearchResponse,
} from "../../types/entities";
import { getSocket, joinTenant } from "../../lib/socket";
import { usePipelineEvents } from "../../hooks/usePipelineEvents";
import { useRealtimeNodes } from "../../hooks/useRealtimeNodes";
import PipelineProgressToast, {
  ToastState,
} from "../../components/graph/PipelineProgressToast";

export function ExplorerContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const initialQuery = searchParams.get("q") ?? "";

  const tenantId = process.env.NEXT_PUBLIC_TENANT_ID ?? "default";

  const [searchQuery, setSearchQuery] = useState(initialQuery);
  const [submitting, setSubmitting] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);

  // Core graph state
  const [evidenceNodes, setEvidenceNodes] = useState<EvidenceNode[]>([]);
  const [evidenceEdges, setEvidenceEdges] = useState<EvidenceEdge[]>([]);

  interface SearchContextUnit {
    context_id: string;
    score: number;
    text: string;
    entity_ids: string[];
  }

  // Selection inspection
  const [selectedNode, setSelectedNode] = useState<EChartsNode | null>(null);

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

  // Join the Socket.io tenant room on mount
  useEffect(() => {
    joinTenant(tenantId);
  }, [tenantId]);

  // Synchronize toastState when alert_publishing finishes (pipeline completed successfully)
  useEffect(() => {
    if (toastState === "running" && stageStatuses.alert_publishing === "done") {
      setToastState("done");
    }
  }, [toastState, stageStatuses.alert_publishing]);

  // 90-second safety fallback timeout for the running toast
  useEffect(() => {
    if (toastState !== "running") return;
    const timer = setTimeout(() => {
      setToastState("done");
    }, 90000); // 90 seconds
    return () => clearTimeout(timer);
  }, [toastState]);

  // Helper mappings
  const mapEntitiesToEvidenceRef = useRef<
    | ((
        entities: Entity[],
        relationships: Relationship[],
        contextUnits?: SearchContextUnit[],
        defaultDepth?: number,
      ) => { nodes: EvidenceNode[]; edges: EvidenceEdge[] })
    | null
  >(null);

  const mapEntitiesToEvidence = useCallback(
    (
      entities: Entity[],
      relationships: Relationship[],
      contextUnits: SearchContextUnit[] = [],
      defaultDepth = 0,
    ): { nodes: EvidenceNode[]; edges: EvidenceEdge[] } => {
      const nodes: EvidenceNode[] = entities.map((entity) => {
        const matchingCtx = contextUnits.find((ctx) =>
          ctx.entity_ids?.includes(entity.id),
        );
        const raw_text = matchingCtx?.text || entity.description || undefined;

        return {
          id: entity.id,
          label: entity.name,
          type: entity.type,
          score: entity.confidence,
          depth: defaultDepth,
          raw_text,
          source_id: entity.source_id || undefined,
          created_at: entity.created || undefined,
        };
      });

      const edges: EvidenceEdge[] = relationships.map((rel) => ({
        id: rel.id,
        source_id: rel.source_ref,
        target_id: rel.target_ref,
        weight: rel.confidence,
      }));

      return { nodes, edges };
    },
    [],
  );

  // Update ref
  useEffect(() => {
    mapEntitiesToEvidenceRef.current = mapEntitiesToEvidence;
  }, [mapEntitiesToEvidence]);

  // Merge real-time entities and relationships when alerts are broadcasted
  useEffect(() => {
    if (newEntities.length > 0 || newRelationships.length > 0) {
      const mapped = mapEntitiesToEvidence(
        newEntities,
        newRelationships,
        [],
        1, // Real-time additions are added at depth 1
      );

      setEvidenceNodes((prev) => {
        const existingIds = new Set(prev.map((n) => n.id));
        const filteredNew = mapped.nodes.filter((n) => !existingIds.has(n.id));
        return filteredNew.length > 0 ? [...prev, ...filteredNew] : prev;
      });

      setEvidenceEdges((prev) => {
        const existingIds = new Set(prev.map((e) => e.id));
        const filteredNew = mapped.edges.filter((e) => !existingIds.has(e.id));
        return filteredNew.length > 0 ? [...prev, ...filteredNew] : prev;
      });

      clearNewEntities();
    }
  }, [newEntities, newRelationships, mapEntitiesToEvidence, clearNewEntities]);

  const runSearch = useCallback(
    async (q: string) => {
      const trimmed = q.trim();
      if (!trimmed) return;
      setSubmitting(true);
      setSearchError(null);
      setErrorDetail(null);
      setCurrentSearchQuery(trimmed);

      try {
        const res = await fetch("/api/query", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            query: trimmed,
            tenant_id: tenantId,
            limit: 50,
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

        const data: SearchResponse & { context_units?: SearchContextUnit[] } =
          await res.json();
        const { nodes, edges } = mapEntitiesToEvidence(
          data.entities || [],
          data.relationships || [],
          data.context_units || [],
          0,
        );

        setEvidenceNodes(nodes);
        setEvidenceEdges(edges);
        setSelectedNode(null);

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
    [tenantId, mapEntitiesToEvidence],
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

  // Node Selection callback
  const handleNodeSelect = (node: EChartsNode) => {
    setSelectedNode(node);
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

      const data: SearchResponse & { context_units?: SearchContextUnit[] } =
        await res.json();
      const mapped = mapEntitiesToEvidence(
        data.entities || [],
        data.relationships || [],
        data.context_units || [],
        nextDepth,
      );

      // Deduplicate State Merge
      setEvidenceNodes((prev) => {
        const existingIds = new Set(prev.map((n) => n.id));
        const newNodes = mapped.nodes.filter((n) => !existingIds.has(n.id));
        return [...prev, ...newNodes];
      });

      setEvidenceEdges((prev) => {
        const existingIds = new Set(prev.map((e) => e.id));
        const newEdges = mapped.edges.filter((e) => !existingIds.has(e.id));
        return [...prev, ...newEdges];
      });
    } catch (err) {
      console.error("Error expanding node:", err);
    }
  };

  const { nodes, links } = transformToEChartsData(evidenceNodes, evidenceEdges);

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
      </header>

      {/* Main Exploration Canvas */}
      <div className="flex-1 relative flex overflow-hidden">
        {searchError && (
          <div className="absolute top-4 left-1/2 -translate-x-1/2 bg-red-950/40 border border-red-900/60 rounded-lg px-4 py-2 text-xs text-red-200 flex items-center gap-2 z-10">
            <ShieldAlert size={14} className="text-red-400" />
            <span>{searchError}</span>
          </div>
        )}

        {nodes.length === 0 && !submitting ? (
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
          </div>
        ) : (
          <div className="flex-1 h-full w-full relative">
            <EChartsGraphCanvas
              nodes={nodes}
              links={links}
              onNodeSelect={handleNodeSelect}
              onNodeDrillDown={handleNodeDrillDown}
            />
          </div>
        )}

        {/* Dynamic slide-out inspect sidebar */}
        <SourceTracePane
          selectedNode={selectedNode}
          onClose={() => setSelectedNode(null)}
        />

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
