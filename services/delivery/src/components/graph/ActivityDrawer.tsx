"use client";

/**
 * ActivityDrawer — collapsible bottom drawer showing live processor pipeline activity.
 *
 * Always-visible handle bar at the bottom of the screen.
 * Expands to show:
 *   1. Stage progress — 7-stage pipeline bar with per-stage status icons
 *   2. Event log — scrollable, newest-first list of all received stage events
 */

import { useRef, useState } from "react";
import type { Socket } from "socket.io-client";
import {
  Activity,
  AlertCircle,
  CheckCircle,
  ChevronDown,
  ChevronUp,
  Circle,
  Loader,
} from "lucide-react";

import { usePipelineEvents, type StageStatus } from "@/hooks/usePipelineEvents";

// ─── Stage metadata ───────────────────────────────────────────────────────────

interface StageInfo {
  key: string;
  label: string;
  detail: string;
}

const PIPELINE_STAGES: StageInfo[] = [
  {
    key: "schema_validation",
    label: "Schema Validation",
    detail: "Envelope check · DLQ routing",
  },
  {
    key: "deduplication",
    label: "Deduplication",
    detail: "Redis SHA-256 content hash",
  },
  {
    key: "llm_extraction",
    label: "LLM Extraction",
    detail: "STIX entity identification",
  },
  {
    key: "entity_resolution",
    label: "Entity Resolution",
    detail: "Qdrant + Neo4j matching",
  },
  {
    key: "graph_persistence",
    label: "Graph Persistence",
    detail: "Neo4j STIX write",
  },
  {
    key: "graphrag_index",
    label: "GraphRAG Index",
    detail: "Community summaries",
  },
  {
    key: "alert_publishing",
    label: "Alert Publishing",
    detail: "analyst-alerts topic",
  },
];

const STAGE_LABEL: Record<string, string> = Object.fromEntries(
  PIPELINE_STAGES.map(({ key, label }) => [key, label]),
);

// ─── Helpers ─────────────────────────────────────────────────────────────────

function relativeTime(receivedAt: number): string {
  const secs = Math.floor((Date.now() - receivedAt) / 1000);
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  return `${Math.floor(mins / 60)}h ago`;
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function StageIcon({ status }: { status: StageStatus }) {
  switch (status) {
    case "done":
      return <CheckCircle className="w-4 h-4 text-emerald-400 shrink-0" />;
    case "active":
      return (
        <Loader className="w-4 h-4 text-indigo-400 shrink-0 animate-spin" />
      );
    default:
      return <Circle className="w-4 h-4 text-slate-700 shrink-0" />;
  }
}

function StageProgressSection({
  stageStatuses,
}: {
  stageStatuses: Record<string, StageStatus>;
}) {
  return (
    <div className="px-4 py-3 border-b border-slate-700">
      <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-2">
        Pipeline Stages
      </p>
      <ol className="grid grid-cols-7 gap-1">
        {PIPELINE_STAGES.map(({ key, label }) => {
          const status = stageStatuses[key] ?? "idle";
          return (
            <li key={key} className="flex flex-col items-center gap-1 min-w-0">
              <StageIcon status={status} />
              <span
                className={`text-[10px] text-center leading-tight truncate w-full ${
                  status === "done"
                    ? "text-emerald-400"
                    : status === "active"
                      ? "text-indigo-400"
                      : "text-slate-600"
                }`}
                title={label}
              >
                {label}
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function StatusBadge({ status }: { status: "active" | "done" }) {
  return status === "active" ? (
    <span className="inline-flex items-center gap-1 text-[10px] font-medium px-1.5 py-0.5 rounded bg-indigo-950 text-indigo-400 border border-indigo-800">
      <Loader className="w-2.5 h-2.5 animate-spin" />
      active
    </span>
  ) : (
    <span className="inline-flex items-center gap-1 text-[10px] font-medium px-1.5 py-0.5 rounded bg-emerald-950 text-emerald-400 border border-emerald-800">
      <CheckCircle className="w-2.5 h-2.5" />
      done
    </span>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

interface Props {
  socket: Socket;
}

export default function ActivityDrawer({ socket }: Props) {
  const { events, stageStatuses, isActive } = usePipelineEvents(socket);
  const [open, setOpen] = useState(false);
  const logRef = useRef<HTMLDivElement>(null);

  const eventCount = events.length;

  return (
    <div
      className="shrink-0 border-t border-slate-700 bg-slate-900"
      data-testid="activity-drawer"
    >
      {/* ── Collapsed handle ─────────────────────────────────────────────── */}
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between px-4 py-2 hover:bg-slate-800 transition-colors"
        aria-expanded={open}
        aria-label="Toggle pipeline activity drawer"
      >
        <div className="flex items-center gap-2">
          {isActive ? (
            <Activity className="w-4 h-4 text-indigo-400 animate-pulse" />
          ) : (
            <Activity className="w-4 h-4 text-slate-500" />
          )}
          <span className="text-sm font-medium text-slate-300">
            Pipeline Activity
          </span>
          {isActive && (
            <span className="text-xs text-indigo-400 animate-pulse">
              Processing…
            </span>
          )}
          {eventCount > 0 && (
            <span className="text-xs bg-slate-700 text-slate-300 rounded-full px-2 py-0.5">
              {eventCount}
            </span>
          )}
        </div>
        {open ? (
          <ChevronDown className="w-4 h-4 text-slate-500" />
        ) : (
          <ChevronUp className="w-4 h-4 text-slate-500" />
        )}
      </button>

      {/* ── Expanded content ─────────────────────────────────────────────── */}
      {open && (
        <div className="flex flex-col" style={{ maxHeight: "40vh" }}>
          {/* Stage progress bar */}
          <StageProgressSection stageStatuses={stageStatuses} />

          {/* Event log */}
          <div
            ref={logRef}
            className="flex-1 overflow-y-auto bg-slate-950"
            data-testid="activity-event-log"
          >
            {eventCount === 0 ? (
              <p className="text-xs text-slate-600 text-center py-6">
                No pipeline events yet. Submit a search to see processor
                activity.
              </p>
            ) : (
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-slate-900 border-b border-slate-700">
                  <tr>
                    <th className="text-left px-4 py-1.5 text-slate-500 font-medium w-1/3">
                      Stage
                    </th>
                    <th className="text-left px-2 py-1.5 text-slate-500 font-medium w-24">
                      Status
                    </th>
                    <th className="text-left px-2 py-1.5 text-slate-500 font-medium">
                      Time
                    </th>
                    <th className="text-left px-2 py-1.5 text-slate-500 font-medium hidden sm:table-cell">
                      Event ID
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {events.map((ev, i) => (
                    <tr
                      key={`${ev.event_id}-${ev.stage}-${ev.receivedAt}-${i}`}
                      className="border-b border-slate-800 hover:bg-slate-900 transition-colors"
                    >
                      <td className="px-4 py-1.5 text-slate-300 font-medium">
                        {STAGE_LABEL[ev.stage] ?? ev.stage}
                      </td>
                      <td className="px-2 py-1.5">
                        <StatusBadge status={ev.status} />
                      </td>
                      <td className="px-2 py-1.5 text-slate-500">
                        {relativeTime(ev.receivedAt)}
                      </td>
                      <td className="px-2 py-1.5 text-slate-600 font-mono truncate max-w-[12rem] hidden sm:table-cell">
                        {ev.event_id || "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
