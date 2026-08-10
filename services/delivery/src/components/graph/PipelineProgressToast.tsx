"use client";

/**
 * PipelineProgressToast — floating bottom-right ingestion monitor (M6 UX).
 *
 * States:
 *   idle     → not rendered
 *   running  → stage checklist from live socket pipeline_stage events
 *   done     → green completion card with "Refresh Workspace" CTA
 *   error    → red diagnostic card showing server error details with Retry/Dismiss
 *
 * Ingestion Fallback behaviour:
 *   - HTTP 4xx/5xx from /api/search is surfaced verbatim so analysts know
 *     exactly what the Aggregator rejected (schema violations, plugin errors, etc.)
 *   - The toast transitions from "running" → "error" without blocking the rest
 *     of the workspace.
 *
 * B7: Dismissed errors are pushed into the notification log via useNotificationLog.
 */

import { useState, useEffect, useRef } from "react";
import {
  Activity,
  AlertCircle,
  CheckCircle,
  ChevronDown,
  ChevronUp,
  Circle,
  Loader,
  RefreshCw,
  X,
} from "lucide-react";

import type { Socket } from "socket.io-client";
import { usePipelineEvents, type StageStatus } from "@/hooks/usePipelineEvents";
import { useNotificationLog } from "@/hooks/useNotificationLog";

// ─── Types ────────────────────────────────────────────────────────────────────

export type ToastState = "idle" | "running" | "done" | "error";

// StageStatus is imported from usePipelineEvents via the hook

const PIPELINE_STAGES: { key: string; label: string }[] = [
  { key: "schema_validation", label: "Validating schema" },
  { key: "deduplication", label: "Deduplicating content" },
  { key: "ner_extraction", label: "Extracting entities (NER)" },
  { key: "entity_resolution", label: "Resolving entities" },
  { key: "graph_persistence", label: "Writing to Knowledge Graph" },
  { key: "alert_publishing", label: "Publishing analyst alerts" },
];

// ─── Props ────────────────────────────────────────────────────────────────────

export interface PipelineProgressToastProps {
  /** The search query currently being processed — shown as context label. */
  query: string;
  /** Overall ingestion state driven by the parent dashboard page. */
  toastState: ToastState;
  /**
   * Detailed error message from the server (e.g. "422: payload missing content key").
   * Shown verbatim inside the error card.
   */
  errorDetail: string | null;
  /** Live socket connection so the toast can subscribe to pipeline_stage events. */
  socket: Socket;
  /** Called when "Refresh Workspace" is pressed after a successful ingestion. */
  onRefreshGraph: () => void;
  /** Called when the analyst dismisses the toast (any state). */
  onDismiss: () => void;
  /** Called when the analyst presses "Retry" inside the error card. */
  onRetry: () => void;
}

// ─── Stage icon helper ────────────────────────────────────────────────────────

function StageIcon({ status }: { status: StageStatus }) {
  if (status === "done")
    return <CheckCircle size={13} className="text-emerald-400 shrink-0" />;
  if (status === "active")
    return (
      <Loader size={13} className="text-indigo-400 animate-spin shrink-0" />
    );
  return <Circle size={13} className="text-slate-600 shrink-0" />;
}

// ─── Component ────────────────────────────────────────────────────────────────

export default function PipelineProgressToast({
  query,
  toastState,
  errorDetail,
  socket,
  onRefreshGraph,
  onDismiss,
  onRetry,
}: PipelineProgressToastProps) {
  const [collapsed, setCollapsed] = useState(false);
  const { pushNotification } = useNotificationLog();

  // Always-on listener via usePipelineEvents — avoids the timing bug where
  // conditional socket.on registration misses early stage events that arrive
  // before the "running" effect re-registers.
  const { stageStatuses } = usePipelineEvents(socket);

  // ── B7: Push dismissed errors into the notification log ────────────────
  // Track whether the current error has been logged so we only push once.
  const lastErrorLoggedRef = useRef<string | null>(null);

  useEffect(() => {
    if (toastState === "error" && errorDetail) {
      // Only log when error detail changes (so retry → new error logs again)
      if (lastErrorLoggedRef.current !== errorDetail) {
        lastErrorLoggedRef.current = errorDetail;
        pushNotification("error", errorDetail);
      }
    }
    if (toastState === "done") {
      pushNotification(
        "success",
        `Pipeline complete for "${query.slice(0, 50)}"`,
      );
    }
  }, [toastState, errorDetail, query, pushNotification]);

  // ── Nothing to show ────────────────────────────────────────────────────────
  if (toastState === "idle") return null;

  const truncatedQuery = query.length > 28 ? `${query.slice(0, 28)}…` : query;

  // ── Shared wrapper ─────────────────────────────────────────────────────────
  return (
    <div
      className="fixed bottom-5 right-5 z-50 w-72 rounded-xl shadow-2xl border overflow-hidden"
      style={{
        borderColor:
          toastState === "error"
            ? "#ef4444"
            : toastState === "done"
              ? "#10b981"
              : "#4f46e5",
        backgroundColor: "#0f172a",
      }}
      role="status"
      aria-live="polite"
      aria-label="Ingestion progress"
    >
      {/* ── Header bar ──────────────────────────────────────────────────────── */}
      <div
        className="flex items-center gap-2 px-3 py-2 cursor-pointer select-none"
        style={{
          backgroundColor:
            toastState === "error"
              ? "rgba(239,68,68,0.15)"
              : toastState === "done"
                ? "rgba(16,185,129,0.12)"
                : "rgba(79,70,229,0.15)",
        }}
        onClick={() => setCollapsed((c) => !c)}
        role="button"
        aria-expanded={!collapsed}
      >
        {toastState === "error" ? (
          <AlertCircle size={14} className="text-red-400 shrink-0" />
        ) : toastState === "done" ? (
          <CheckCircle size={14} className="text-emerald-400 shrink-0" />
        ) : (
          <Activity
            size={14}
            className="text-indigo-400 shrink-0 animate-pulse"
          />
        )}

        <span className="flex-1 text-xs font-semibold text-slate-200 truncate">
          {toastState === "error"
            ? "Ingestion failed"
            : toastState === "done"
              ? "Pipeline complete"
              : `Processing "${truncatedQuery}"`}
        </span>

        <button
          onClick={(e) => {
            e.stopPropagation();
            onDismiss();
          }}
          className="text-slate-500 hover:text-slate-200 transition-colors ml-1"
          aria-label="Dismiss"
        >
          <X size={13} />
        </button>

        {collapsed ? (
          <ChevronUp size={13} className="text-slate-500" />
        ) : (
          <ChevronDown size={13} className="text-slate-500" />
        )}
      </div>

      {/* ── Body ────────────────────────────────────────────────────────────── */}
      {!collapsed && (
        <div className="px-3 py-3 space-y-3">
          {/* ── Running: stage checklist ────────────────────────────────────── */}
          {(toastState === "running" || toastState === "done") && (
            <ol className="space-y-1.5">
              {PIPELINE_STAGES.map((s) => {
                const status = stageStatuses[s.key] ?? "idle";
                return (
                  <li key={s.key} className="flex items-center gap-2">
                    <StageIcon status={status} />
                    <span
                      className={`text-xs ${
                        status === "done"
                          ? "text-slate-300 line-through decoration-slate-600"
                          : status === "active"
                            ? "text-slate-100 font-medium"
                            : "text-slate-600"
                      }`}
                    >
                      {s.label}
                    </span>
                  </li>
                );
              })}
            </ol>
          )}

          {/* ── Done: refresh CTA ───────────────────────────────────────────── */}
          {toastState === "done" && (
            <button
              onClick={onRefreshGraph}
              className="w-full flex items-center justify-center gap-2 text-xs font-semibold bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg py-2 transition-colors"
            >
              <RefreshCw size={12} />
              Refresh Workspace
            </button>
          )}

          {/* ── Error: diagnostic card ──────────────────────────────────────── */}
          {toastState === "error" && (
            <div className="space-y-2">
              {errorDetail && (
                <div className="bg-red-950/50 border border-red-900/50 rounded-lg p-2">
                  <p className="text-red-300 text-[10px] font-mono leading-relaxed break-words whitespace-pre-wrap">
                    {errorDetail}
                  </p>
                </div>
              )}
              <div className="flex gap-2">
                <button
                  onClick={onRetry}
                  className="flex-1 text-xs font-semibold bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg py-1.5 transition-colors"
                >
                  Retry
                </button>
                <button
                  onClick={onDismiss}
                  className="flex-1 text-xs font-semibold bg-slate-700 hover:bg-slate-600 text-slate-200 rounded-lg py-1.5 transition-colors"
                >
                  Dismiss
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
