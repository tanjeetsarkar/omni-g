"use client";

/**
 * /dashboard — Omni-G Intelligence Workstation (M6 UX).
 *
 * Layout:
 *   ┌────────────────────────────────────────────────────────┐
 *   │ Header: logo · search bar · view toggle · alert badge  │
 *   ├────────────────────────────────────────────────────────┤
 *   │ FilterToolbar (node type pills, confidence, label)     │
 *   ├────────────────────────────────────┬───────────────────┤
 *   │  Main view:                        │ FocusPanel        │
 *   │   "network" → Sigma.js WebGL map   │ (Entity + Audio   │
 *   │   "canvas"  → ConceptFlowView      │  Briefings tabs)  │
 *   └────────────────────────────────────┴───────────────────┘
 *   │ ActivityDrawer (bottom, collapsible)                   │
 *   └────────────────────────────────────────────────────────┘
 *   ╭── PipelineProgressToast (bottom-right, floating) ──────╮
 *
 * New in M6:
 *   1. Header search bar — background ingestion without leaving workspace.
 *   2. PipelineProgressToast — live stage ticks + verbose error fallbacks.
 *   3. In-place graph refresh via "Refresh Workspace" CTA in toast.
 *   4. Dual view toggle — WebGL Network Map ↔ Concept Canvas.
 *   5. FocusPanel now has Entity + Briefings tabs.
 */

import dynamic from "next/dynamic";
import {
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useSearchParams } from "next/navigation";
import { Network, Workflow as CanvasIcon, Search, Loader } from "lucide-react";

import ActivityDrawer from "@/components/graph/ActivityDrawer";
import AlertBadge from "@/components/graph/AlertBadge";
import FilterToolbar from "@/components/graph/FilterToolbar";
import FocusPanel from "@/components/graph/FocusPanel";
import PipelineProgressToast, {
  type ToastState,
} from "@/components/graph/PipelineProgressToast";
import { useAlertHighlight } from "@/hooks/useAlertHighlight";
import { useGraphFilter } from "@/hooks/useGraphFilter";
import { useSemanticZoom } from "@/hooks/useSemanticZoom";
import { buildClusterGraph } from "@/lib/buildClusterGraph";
import { getSocket, joinTenant } from "@/lib/socket";
import type { GraphNode, GraphEdge } from "@/types/graph";

// GraphView uses Sigma.js (WebGL) — must be client-only, no SSR
const GraphView = dynamic(() => import("@/components/graph/GraphView"), {
  ssr: false,
  loading: () => (
    <div className="flex items-center justify-center w-full h-full">
      <p className="text-slate-400 text-sm animate-pulse">
        Initialising graph…
      </p>
    </div>
  ),
});

// ConceptFlowView is also client-only (uses DOM APIs for path recalculation)
const ConceptFlowView = dynamic(
  () => import("@/components/graph/ConceptFlowView"),
  {
    ssr: false,
    loading: () => (
      <div className="flex items-center justify-center w-full h-full">
        <p className="text-slate-400 text-sm animate-pulse">Loading canvas…</p>
      </div>
    ),
  },
);

type ViewMode = "network" | "canvas";

// ── useGraphDataWithRefetch ───────────────────────────────────────────────────
// Extends the standard polling hook with a manual refetch handle so the toast
// can trigger an in-place workspace update without a full-page reload.

function useGraphDataWithRefetch() {
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [edges, setEdges] = useState<GraphEdge[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      const res = await fetch("/api/graph");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: { nodes: GraphNode[]; edges: GraphEdge[] } = await res.json();
      setNodes(data.nodes ?? []);
      setEdges(data.edges ?? []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load graph");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 30_000);
    return () => clearInterval(interval);
  }, [fetchData]);

  return { nodes, edges, loading, error, refetch: fetchData };
}

// ── DashboardContent ──────────────────────────────────────────────────────────

function DashboardContent() {
  const socket = getSocket();
  const searchParams = useSearchParams();
  const initialQuery = searchParams.get("q") ?? "";

  const tenantId = process.env.NEXT_PUBLIC_TENANT_ID ?? "default";

  const { nodes, edges, loading, error, refetch } = useGraphDataWithRefetch();
  const { highlightedNodeIds, alertCount } = useAlertHighlight(socket);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);

  // ── View mode ──────────────────────────────────────────────────────────────
  const [viewMode, setViewMode] = useState<ViewMode>("network");

  // ── Semantic zoom (network mode only) ─────────────────────────────────────
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const sigmaRef = useRef<any>(null);
  const [, setSigmaReady] = useState(false);
  const { isClustered } = useSemanticZoom(sigmaRef);

  // ── Filter state ───────────────────────────────────────────────────────────
  const {
    filteredNodes,
    filteredEdges,
    filterState,
    availableTypes,
    toggleType,
    setMinConfidence,
    setSearchQuery,
    resetFilters,
  } = useGraphFilter(nodes, edges);

  const { clusterNodes, clusterEdges } = useMemo(
    () => buildClusterGraph(filteredNodes, filteredEdges),
    [filteredNodes, filteredEdges],
  );

  const displayNodes = isClustered ? clusterNodes : filteredNodes;
  const displayEdges = isClustered ? clusterEdges : filteredEdges;

  useEffect(() => {
    if (initialQuery) setSearchQuery(initialQuery);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialQuery]);

  useEffect(() => {
    joinTenant(tenantId);
  }, [tenantId]);

  // ── Background ingestion ───────────────────────────────────────────────────
  const [headerQuery, setHeaderQuery] = useState("");
  const [toastState, setToastState] = useState<ToastState>("idle");
  const [toastQuery, setToastQuery] = useState("");
  const [ingestError, setIngestError] = useState<string | null>(null);
  const lastQueryRef = useRef("");

  const runIngestion = useCallback(async (q: string) => {
    if (!q.trim()) return;
    lastQueryRef.current = q.trim();
    setToastQuery(q.trim());
    setToastState("running");
    setIngestError(null);

    try {
      const res = await fetch("/api/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: q.trim() }),
      });

      if (!res.ok) {
        let detail: string;
        try {
          const body = await res.json();
          detail = `HTTP ${res.status}: ${body?.detail ?? body?.message ?? JSON.stringify(body)}`;
        } catch {
          detail = `HTTP ${res.status}: ${res.statusText}`;
        }
        setToastState("error");
        setIngestError(detail);
        return;
      }
      // Stays "running" — toast transitions to "done" when the alert arrives below
    } catch (err) {
      const detail =
        err instanceof Error ? err.message : "Unknown network error";
      setToastState("error");
      setIngestError(`Connection error: ${detail}`);
    }
  }, []);

  // First analyst alert after an ingestion run → mark pipeline done
  useEffect(() => {
    if (toastState !== "running") return;
    function handleAlert() {
      setToastState("done");
    }
    socket.on("alert", handleAlert);
    return () => {
      socket.off("alert", handleAlert);
    };
  }, [socket, toastState]);

  function handleHeaderSearch(e: React.FormEvent) {
    e.preventDefault();
    runIngestion(headerQuery);
    setHeaderQuery("");
  }

  function handleRefreshGraph() {
    refetch();
    setToastState("idle");
  }

  return (
    <div
      className="flex flex-col h-screen bg-slate-950 text-slate-100"
      data-testid="dashboard-content"
    >
      {/* ── Top Bar ─────────────────────────────────────────────────────────── */}
      <header className="flex items-center gap-3 px-4 py-2.5 bg-slate-900 border-b border-slate-700 shrink-0">
        {/* Brand */}
        <div className="flex items-center gap-2 shrink-0">
          <span className="font-bold text-base tracking-tight">Omni-G</span>
          <span className="text-[10px] text-slate-500 uppercase tracking-widest hidden sm:block">
            Knowledge Graph
          </span>
        </div>

        <div className="w-px h-5 bg-slate-700 shrink-0" />

        {/* Deep Search & Ingest */}
        <form
          onSubmit={handleHeaderSearch}
          className="flex items-center gap-1.5 flex-1 min-w-0"
          aria-label="Deep search and ingest"
        >
          <div className="relative flex-1 min-w-0 max-w-sm">
            <Search
              size={13}
              className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-500 pointer-events-none"
            />
            <input
              type="text"
              value={headerQuery}
              onChange={(e) => setHeaderQuery(e.target.value)}
              placeholder="Deep search & ingest a topic…"
              className="w-full bg-slate-800 border border-slate-600 text-slate-200 text-xs
                         placeholder-slate-500 rounded-lg pl-7 pr-3 py-1.5
                         focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
            />
          </div>
          <button
            type="submit"
            disabled={!headerQuery.trim() || toastState === "running"}
            className="shrink-0 bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-700
                       disabled:text-slate-500 text-white text-xs font-semibold
                       px-3 py-1.5 rounded-lg transition-colors flex items-center gap-1"
          >
            {toastState === "running" && (
              <Loader size={11} className="animate-spin" />
            )}
            Ingest
          </button>
        </form>

        <div className="flex items-center gap-2 shrink-0 ml-auto">
          {/* View toggle */}
          <div
            className="flex items-center bg-slate-800 border border-slate-700 rounded-lg p-0.5 gap-0.5"
            role="group"
            aria-label="Switch view mode"
          >
            <button
              onClick={() => setViewMode("network")}
              aria-pressed={viewMode === "network"}
              title="Network Map"
              className={`flex items-center gap-1 px-2.5 py-1 rounded text-xs font-medium transition-colors ${
                viewMode === "network"
                  ? "bg-indigo-600 text-white"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <Network size={12} />
              <span className="hidden sm:inline">Network</span>
            </button>
            <button
              onClick={() => setViewMode("canvas")}
              aria-pressed={viewMode === "canvas"}
              title="Concept Canvas"
              className={`flex items-center gap-1 px-2.5 py-1 rounded text-xs font-medium transition-colors ${
                viewMode === "canvas"
                  ? "bg-indigo-600 text-white"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <CanvasIcon size={12} />
              <span className="hidden sm:inline">Canvas</span>
            </button>
          </div>

          <AlertBadge count={alertCount} />
        </div>
      </header>

      {/* ── Filter Toolbar ───────────────────────────────────────────────────── */}
      <FilterToolbar
        availableTypes={availableTypes}
        filterState={filterState}
        onToggleType={toggleType}
        onConfidenceChange={setMinConfidence}
        onSearchChange={setSearchQuery}
        onReset={resetFilters}
        shownNodes={filteredNodes.length}
        totalNodes={nodes.length}
      />

      {/* ── Main Area ────────────────────────────────────────────────────────── */}
      <div className="flex flex-1 min-h-0">
        <main className="flex-1 relative">
          {loading && (
            <div className="absolute inset-0 flex items-center justify-center bg-slate-950/80 z-10">
              <p className="text-slate-400 text-sm animate-pulse">
                Loading graph…
              </p>
            </div>
          )}
          {error && !loading && (
            <div className="absolute inset-0 flex items-center justify-center z-10">
              <p className="text-red-400 text-sm">Error: {error}</p>
            </div>
          )}

          {!loading && viewMode === "network" && (
            <GraphView
              nodes={displayNodes}
              edges={displayEdges}
              highlightedNodeIds={highlightedNodeIds}
              selectedNodeId={selectedNodeId}
              onNodeClick={setSelectedNodeId}
              onSigmaReady={(s) => {
                sigmaRef.current = s;
                setSigmaReady(true);
              }}
              className="w-full h-full"
            />
          )}

          {!loading && viewMode === "canvas" && (
            <ConceptFlowView
              nodes={filteredNodes}
              edges={filteredEdges}
              selectedNodeId={selectedNodeId}
              onNodeClick={setSelectedNodeId}
              className="w-full h-full"
            />
          )}
        </main>

        {/* Focus panel — Entity dossier + Audio Briefings */}
        <FocusPanel
          nodeId={selectedNodeId}
          nodes={nodes}
          tenantId={tenantId}
          onClose={() => setSelectedNodeId(null)}
        />
      </div>

      {/* ── Pipeline Activity Drawer ─────────────────────────────────────────── */}
      <ActivityDrawer socket={socket} />

      {/* ── Floating Ingestion Monitor Toast ─────────────────────────────────── */}
      <PipelineProgressToast
        query={toastQuery}
        toastState={toastState}
        errorDetail={ingestError}
        socket={socket}
        onRefreshGraph={handleRefreshGraph}
        onDismiss={() => {
          setToastState("idle");
          setIngestError(null);
        }}
        onRetry={() => {
          if (lastQueryRef.current) runIngestion(lastQueryRef.current);
        }}
      />
    </div>
  );
}

export default function DashboardPage() {
  return (
    <Suspense fallback={null}>
      <DashboardContent />
    </Suspense>
  );
}
