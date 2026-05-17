"use client";

/**
 * /dashboard — interactive graph dashboard (M5.2)
 *
 * Layout:
 *   ┌──────────────────────────────────┐
 *   │ Top bar: Omni-G  [AlertBadge]    │
 *   ├──────────────────────┬───────────┤
 *   │  GraphView (flex-1)  │FocusPanel │
 *   └──────────────────────┴───────────┘
 */

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";

import AlertBadge from "@/components/graph/AlertBadge";
import FocusPanel from "@/components/graph/FocusPanel";
import { useAlertHighlight } from "@/hooks/useAlertHighlight";
import { useGraphData } from "@/hooks/useGraphData";
import { getSocket, joinTenant } from "@/lib/socket";

// GraphView uses Sigma.js (WebGL) — must be client-only, no SSR
const GraphView = dynamic(() => import("@/components/graph/GraphView"), {
  ssr: false,
  loading: () => (
    <div className="flex items-center justify-center w-full h-full">
      <p className="text-slate-400 text-sm animate-pulse">Initialising graph…</p>
    </div>
  ),
});

export default function DashboardPage() {
  const socket = getSocket();
  const { nodes, edges, loading, error } = useGraphData();
  const { highlightedNodeIds, alertCount } = useAlertHighlight(socket);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);

  // Join the default tenant room on mount
  useEffect(() => {
    const tenantId = process.env.NEXT_PUBLIC_TENANT_ID ?? "default";
    joinTenant(tenantId);
  }, []);

  return (
    <div className="flex flex-col h-screen bg-slate-950 text-slate-100">
      {/* ── Top Bar ───────────────────────────────────────────────────── */}
      <header className="flex items-center justify-between px-6 py-3 bg-slate-900 border-b border-slate-700 shrink-0">
        <div className="flex items-center gap-3">
          <span className="font-bold text-lg tracking-tight">Omni-G</span>
          <span className="text-xs text-slate-500 uppercase tracking-widest">
            Knowledge Graph
          </span>
        </div>
        <AlertBadge count={alertCount} />
      </header>

      {/* ── Main Area ─────────────────────────────────────────────────── */}
      <div className="flex flex-1 min-h-0">
        {/* Graph canvas */}
        <main className="flex-1 relative">
          {loading && (
            <div className="absolute inset-0 flex items-center justify-center bg-slate-950/80 z-10">
              <p className="text-slate-400 text-sm animate-pulse">Loading graph…</p>
            </div>
          )}
          {error && !loading && (
            <div className="absolute inset-0 flex items-center justify-center z-10">
              <p className="text-red-400 text-sm">Error: {error}</p>
            </div>
          )}
          {!loading && (
            <GraphView
              nodes={nodes}
              edges={edges}
              highlightedNodeIds={highlightedNodeIds}
              selectedNodeId={selectedNodeId}
              onNodeClick={setSelectedNodeId}
              className="w-full h-full"
            />
          )}
        </main>

        {/* Focus panel (always rendered; content changes by selectedNodeId) */}
        <FocusPanel
          nodeId={selectedNodeId}
          nodes={nodes}
          onClose={() => setSelectedNodeId(null)}
        />
      </div>
    </div>
  );
}
