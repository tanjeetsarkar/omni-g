"use client";

/**
 * PipelineIndicator — compact inline pipeline progress indicator (V4 Phase 6).
 *
 * Renders below the FloatingSearchBar as a narrow horizontal strip showing:
 *   - Query label (truncated to 40 chars)
 *   - 6 stage pills with status icons (idle / active / done / error)
 *   - Elapsed time since pipeline start
 *
 * Only visible when at least one stage is "active" or "done".
 * Replaces the ActivityDrawer (bottom drawer) + PipelineProgressToast (floating card).
 */

import { useEffect, useRef, useState } from "react";
import type { Socket } from "socket.io-client";
import { CheckCircle, Loader, Circle, AlertCircle } from "lucide-react";

import { usePipelineEvents, type StageStatus } from "@/hooks/usePipelineEvents";

// ─── Stage definitions ────────────────────────────────────────────────────────

const PIPELINE_STAGES = [
  { key: "schema_validation", label: "Schema" },
  { key: "deduplication", label: "Dedup" },
  { key: "ner_extraction", label: "NER" },
  { key: "entity_resolution", label: "Resolution" },
  { key: "graph_persistence", label: "Graph" },
  { key: "alert_publishing", label: "Alert" },
] as const;

// ─── Helpers ─────────────────────────────────────────────────────────────────

function formatElapsed(ms: number): string {
  const secs = Math.floor(ms / 1000);
  if (secs < 60) return `${secs}s`;
  const mins = Math.floor(secs / 60);
  const remainSecs = secs % 60;
  return `${mins}m ${remainSecs}s`;
}

function StagePill({
  status,
  label,
  error,
}: {
  status: StageStatus;
  label: string;
  error?: string;
}) {
  if (status === "error") {
    return (
      <span
        className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-red-950/60 text-red-400 border border-red-800/50"
        title={error ?? `${label} failed`}
      >
        <AlertCircle size={10} className="shrink-0" />
        {label}
      </span>
    );
  }

  if (status === "done") {
    return (
      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-emerald-950/40 text-emerald-400 border border-emerald-800/50">
        <CheckCircle size={10} className="shrink-0" />
        {label}
      </span>
    );
  }

  if (status === "active") {
    return (
      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-indigo-950/50 text-indigo-400 border border-indigo-800/50">
        <Loader size={10} className="shrink-0 animate-spin" />
        {label}
      </span>
    );
  }

  // idle
  return (
    <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium text-slate-600 border border-slate-700/50">
      <Circle size={10} className="shrink-0" />
      {label}
    </span>
  );
}

// ─── Props ────────────────────────────────────────────────────────────────────

interface PipelineIndicatorProps {
  socket: Socket;
  activeSearchId?: string | null;
  query: string;
}

// ─── Component ────────────────────────────────────────────────────────────────

export function PipelineIndicator({ socket, query }: PipelineIndicatorProps) {
  const { stageStatuses, isActive } = usePipelineEvents(socket);
  const [startTime, setStartTime] = useState<number | null>(null);
  const [showWaiting, setShowWaiting] = useState(false);

  // Track when the pipeline started (first stage becomes active)
  const prevActiveRef = useRef(isActive);
  useEffect(() => {
    if (isActive && !prevActiveRef.current) {
      setStartTime(Date.now());
      setShowWaiting(false);
    }
    if (!isActive) {
      // Keep the start time for a brief moment after completion so the user
      // sees the final elapsed time before the indicator disappears.
      const timer = setTimeout(() => setStartTime(null), 5000);
      prevActiveRef.current = isActive;
      return () => clearTimeout(timer);
    }
    prevActiveRef.current = isActive;
  }, [isActive]);

  // Show "waiting" state when there's an active query but no pipeline events yet.
  // After 8 seconds with no events, hide the indicator (pipeline may not be running).
  useEffect(() => {
    if (!query.trim()) {
      setShowWaiting(false);
      return;
    }
    if (isActive) return; // pipeline is running, don't show waiting

    const hasAnyStage = Object.values(stageStatuses).some(
      (s) => s === "active" || s === "done" || s === "error",
    );
    if (hasAnyStage) {
      setShowWaiting(false);
      return;
    }

    // Show waiting state briefly, then hide if nothing happens.
    setShowWaiting(true);
    const timer = setTimeout(() => setShowWaiting(false), 8000);
    return () => clearTimeout(timer);
  }, [query, isActive, stageStatuses]);

  const hasAnyStage = Object.values(stageStatuses).some(
    (s) => s === "active" || s === "done" || s === "error",
  );

  // Only render when there's pipeline activity OR we're waiting for it.
  if (!hasAnyStage && !showWaiting) return null;

  const truncatedQuery = query.length > 40 ? `${query.slice(0, 40)}…` : query;

  return (
    <div
      className="absolute top-[68px] left-1/2 -translate-x-1/2 z-30 flex items-center gap-3 px-3 py-1.5 bg-slate-900/85 backdrop-blur-md border border-slate-700/50 rounded-full shadow-xl text-xs pointer-events-none"
      role="status"
      aria-live="polite"
      aria-label="Pipeline progress"
    >
      {/* Query label */}
      <span
        className="text-slate-400 truncate max-w-[140px]"
        title={query || undefined}
      >
        {truncatedQuery || "Processing…"}
      </span>

      {/* Stage pills */}
      <div className="flex items-center gap-1 flex-1 justify-center">
        {showWaiting && !hasAnyStage ? (
          <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[10px] font-medium text-indigo-400 bg-indigo-950/50 border border-indigo-800/50">
            <Loader size={10} className="shrink-0 animate-spin" />
            Starting pipeline…
          </span>
        ) : (
          PIPELINE_STAGES.map(({ key, label }) => {
            const status = stageStatuses[key] ?? "idle";
            return <StagePill key={key} status={status} label={label} />;
          })
        )}
      </div>

      {/* Elapsed time */}
      {startTime !== null && (
        <span className="text-slate-500 tabular-nums shrink-0 min-w-[4ch] text-right">
          {formatElapsed(Date.now() - startTime)}
        </span>
      )}
    </div>
  );
}
