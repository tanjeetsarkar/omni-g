"use client";

/**
 * /dashboard — Omni-G Knowledge Graph Search-First Dashboard (M5.2 / M2.3).
 *
 * Layout:
 *   ┌────────────────────────────────────────────────────────┐
 *   │ Header: logo · search bar                              │
 *   ├────────────────────────────────────────────────────────┤
 *   │  KnowledgeGraph (React Flow canvas — empty until       │
 *   │  first search)                                         │
 *   └────────────────────────────────────────────────────────┘
 *   ╭── PipelineProgressToast (bottom-right, floating) ──────╮
 *   ╭── ActivityDrawer (bottom, collapsible) ─────────────────╮
 */

import dynamic from "next/dynamic";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Search, Loader } from "lucide-react";

import ActivityDrawer from "@/components/graph/ActivityDrawer";
import PipelineProgressToast, {
  type ToastState,
} from "@/components/graph/PipelineProgressToast";
import { getSocket, joinTenant } from "@/lib/socket";
import { useRealtimeNodes } from "@/hooks/useRealtimeNodes";
import type { SearchResponse } from "@/types/entities";

// KnowledgeGraph uses React Flow — must be client-only, no SSR
const KnowledgeGraph = dynamic(
  () =>
    import("@/components/graph/KnowledgeGraph").then((m) => ({
      default: m.KnowledgeGraph,
    })),
  {
    ssr: false,
    loading: () => (
      <div className="flex items-center justify-center w-full h-full">
        <p className="text-slate-400 text-sm animate-pulse">
          Initialising graph…
        </p>
      </div>
    ),
  },
);

// ── DashboardContent ──────────────────────────────────────────────────────────

function DashboardContent() {
  const socket = getSocket();
  const searchParams = useSearchParams();
  const initialQuery = searchParams.get("q") ?? "";

  const tenantId = process.env.NEXT_PUBLIC_TENANT_ID ?? "default";

  const [searchQuery, setSearchQuery] = useState(initialQuery);
  const [submitting, setSubmitting] = useState(false);
  const [searchResult, setSearchResult] = useState<SearchResponse>({
    entities: [],
    relationships: [],
  });
  const [searchError, setSearchError] = useState<string | null>(null);

  const [toastState, setToastState] = useState<ToastState>("idle");
  const [toastQuery, setToastQuery] = useState("");
  const [ingestError, setIngestError] = useState<string | null>(null);
  const lastQueryRef = useRef("");

  const { newEntities } = useRealtimeNodes({ tenantId });

  // Join tenant room on mount
  useEffect(() => {
    joinTenant(tenantId);
  }, [socket, tenantId]);

  // Auto-search when arriving via ?q=
  useEffect(() => {
    if (initialQuery) {
      runSearch(initialQuery);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /**
   * refreshGraph — queries already-ingested entities from the Processor via
   * Qdrant semantic search + Neo4j neighbour expansion and updates the graph
   * canvas.  Called immediately when a search is submitted (to show existing
   * data right away) and again on pipeline_complete (to show freshly ingested
   * entities).
   */
  const refreshGraph = useCallback(
    async (q: string) => {
      const trimmed = q.trim();
      if (!trimmed) return;
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
          setSearchError(err.error ?? `Graph query failed: HTTP ${res.status}`);
          return;
        }
        const data: SearchResponse = await res.json();
        setSearchResult(data);
        setSearchError(null);
      } catch (err) {
        const detail =
          err instanceof Error ? err.message : "Graph query failed";
        setSearchError(detail);
      }
    },
    [tenantId],
  );

  /**
   * runSearch — immediately queries existing entities (search-first UX) then
   * triggers on-demand ingestion via the Aggregator so new data is gathered
   * in the background.  The Aggregator fans out to MCP plugins, queues Kafka
   * events, and returns 202.  The toast stays "running" until the processor
   * emits alert_publishing→done via the WebSocket.
   */
  const runSearch = useCallback(
    async (q: string) => {
      const trimmed = q.trim();
      if (!trimmed) return;
      setSubmitting(true);
      setSearchError(null);
      setToastQuery(trimmed);
      setToastState("running");
      setIngestError(null);
      lastQueryRef.current = trimmed;

      // ── Step 1: Immediately show already-ingested entities (search-first) ──
      // Don't await — let the graph populate while ingestion runs in parallel.
      void refreshGraph(trimmed);

      // ── Step 2: Trigger on-demand ingestion for new / updated data ─────────
      try {
        const res = await fetch("/api/search", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ query: trimmed, sources: [] }),
        });
        if (!res.ok) {
          const err: { error?: string } = await res.json().catch(() => ({}));
          throw new Error(err.error ?? `HTTP ${res.status}`);
        }
        // 202 Accepted — pipeline is running; toast transitions via socket event
      } catch (err) {
        const detail = err instanceof Error ? err.message : "Unknown error";
        setSearchError(detail);
        setToastState("error");
        setIngestError(detail);
      } finally {
        setSubmitting(false);
      }
    },
    [refreshGraph],
  );

  // Transition toast to "done" and auto-refresh graph when the last pipeline
  // stage (alert_publishing) completes.
  useEffect(() => {
    if (toastState !== "running") return;
    function handlePipelineComplete(ev: unknown) {
      const event = ev as Record<string, unknown>;
      if (event.stage === "alert_publishing" && event.status === "done") {
        setToastState("done");
        if (lastQueryRef.current) {
          refreshGraph(lastQueryRef.current);
        }
      }
    }
    socket.on("pipeline_stage", handlePipelineComplete);
    return () => {
      socket.off("pipeline_stage", handlePipelineComplete);
    };
  }, [socket, toastState, refreshGraph]);

  // 90-second fallback: if the socket never delivers pipeline_complete
  // (gateway down, missed event), transition the toast and refresh anyway.
  useEffect(() => {
    if (toastState !== "running") return;
    const timeoutId = setTimeout(() => {
      setToastState("done");
      if (lastQueryRef.current) {
        refreshGraph(lastQueryRef.current);
      }
    }, 90_000);
    return () => clearTimeout(timeoutId);
  }, [toastState, refreshGraph]);

  function handleSearchSubmit(e: React.FormEvent) {
    e.preventDefault();
    runSearch(searchQuery);
  }

  return (
    <div
      className="flex flex-col h-screen bg-slate-950 text-slate-100"
      data-testid="dashboard-content"
    >
      {/* ── Top Bar ─────────────────────────────────────────────────────────── */}
      <header className="flex items-center gap-3 px-4 py-2.5 bg-slate-900 border-b border-slate-700 shrink-0">
        <div className="flex items-center gap-2 shrink-0">
          <span className="font-bold text-base tracking-tight">Omni-G</span>
          <span className="text-[10px] text-slate-500 uppercase tracking-widest hidden sm:block">
            Knowledge Graph
          </span>
        </div>

        <div className="w-px h-5 bg-slate-700 shrink-0" />

        <form
          onSubmit={handleSearchSubmit}
          className="flex items-center gap-1.5 flex-1 min-w-0"
          aria-label="Search knowledge graph"
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
              placeholder="Search entities, people, topics…"
              className="w-full bg-slate-800 border border-slate-600 text-slate-200 text-xs
                         placeholder-slate-500 rounded-lg pl-7 pr-3 py-1.5
                         focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
              disabled={submitting}
              autoFocus
            />
          </div>
          <button
            type="submit"
            disabled={!searchQuery.trim() || submitting}
            className="shrink-0 bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-700
                       disabled:text-slate-500 text-white text-xs font-semibold
                       px-3 py-1.5 rounded-lg transition-colors flex items-center gap-1"
          >
            {submitting && <Loader size={11} className="animate-spin" />}
            Search
          </button>
        </form>

        {/* Result count */}
        {searchResult.entities.length > 0 && (
          <span className="text-xs text-slate-400 shrink-0 hidden sm:block">
            {searchResult.entities.length} entities
          </span>
        )}
      </header>

      {/* ── Graph Canvas ─────────────────────────────────────────────────────── */}
      <main className="flex-1 relative min-h-0">
        {searchError && (
          <div className="absolute top-4 left-1/2 -translate-x-1/2 z-10 bg-red-900/80 border border-red-700 text-red-200 text-xs px-4 py-2 rounded-lg">
            {searchError}
          </div>
        )}

        <KnowledgeGraph
          entities={searchResult.entities}
          relationships={searchResult.relationships}
          newEntities={newEntities}
        />
      </main>

      {/* ── Pipeline Activity Drawer ─────────────────────────────────────────── */}
      <ActivityDrawer socket={socket} />

      {/* ── Floating Pipeline Monitor Toast ──────────────────────────────────── */}
      <PipelineProgressToast
        query={toastQuery}
        toastState={toastState}
        errorDetail={ingestError}
        socket={socket}
        onRefreshGraph={() => {
          if (lastQueryRef.current) refreshGraph(lastQueryRef.current);
        }}
        onDismiss={() => {
          setToastState("idle");
          setIngestError(null);
        }}
        onRetry={() => {
          if (lastQueryRef.current) runSearch(lastQueryRef.current);
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
