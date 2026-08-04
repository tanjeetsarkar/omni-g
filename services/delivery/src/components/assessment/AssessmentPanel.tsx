"use client";

import { useState } from "react";
import {
  ChevronDown,
  ChevronUp,
  ShieldCheck,
  AlertTriangle,
  CircleDot,
  ChevronRight,
} from "lucide-react";
import type { Assessment } from "@/types/assessment";

/**
 * AssessmentPanel — BLUF-first V2 assessment display.
 *
 * Layout (collapsed → shows only conclusion + confidence):
 *
 *   ┌──────────────────────────────────────────────────────┐
 *   │ BLUF  [PUBLISHED]                    [▲ Collapse]   │
 *   │ "Acme Corp is probably planning …"                   │
 *   │ Confidence: ████████░░  60%  (50%–75%)              │
 *   ├──────────────────────────────────────────────────────┤
 *   │ Reasoning …                                          │
 *   │ Supporting evidence (N)  |  Contradicting (N)        │
 *   │ Intelligence gaps (N)                                │
 *   │ Recommended next actions                             │
 *   └──────────────────────────────────────────────────────┘
 */

interface AssessmentPanelProps {
  assessment: Assessment;
  onDismiss?: () => void;
}

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color =
    pct >= 70 ? "bg-emerald-500" : pct >= 40 ? "bg-yellow-500" : "bg-red-500";

  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-slate-700 rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full ${color}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-xs text-slate-300 tabular-nums w-8 text-right">
        {pct}%
      </span>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colours: Record<string, string> = {
    PUBLISHED: "bg-emerald-900/60 text-emerald-300 border-emerald-700",
    READY: "bg-blue-900/60 text-blue-300 border-blue-700",
    DRAFT: "bg-slate-700/60 text-slate-400 border-slate-600",
    SUPERSEDED: "bg-amber-900/60 text-amber-300 border-amber-700",
  };
  const cls =
    colours[status] ?? "bg-slate-700/60 text-slate-400 border-slate-600";
  return (
    <span
      className={`text-[10px] font-semibold uppercase tracking-widest px-1.5 py-0.5 rounded border ${cls}`}
    >
      {status}
    </span>
  );
}

export function AssessmentPanel({
  assessment,
  onDismiss,
}: AssessmentPanelProps) {
  const [expanded, setExpanded] = useState(true);

  const { confidence } = assessment;
  const midPct = Math.round(confidence.mid * 100);
  const lowPct = Math.round(confidence.low * 100);
  const highPct = Math.round(confidence.high * 100);

  const supportCount = assessment.supporting_evidence_ids.length;
  const contradictCount = assessment.contradicting_evidence_ids.length;
  const gapCount = assessment.collection_gaps.length;

  return (
    <aside
      className="flex flex-col bg-slate-900 border border-slate-700 rounded-lg overflow-hidden text-slate-100"
      aria-label="Assessment panel"
      data-testid="assessment-panel"
    >
      {/* ── BLUF Header (always visible) ───────────────────────────────────── */}
      <div className="px-4 pt-3 pb-2">
        <div className="flex items-start justify-between gap-2 mb-2">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[10px] font-bold uppercase tracking-widest text-indigo-400">
              BLUF
            </span>
            <StatusBadge status={assessment.status} />
            <span className="text-[10px] text-slate-500">
              v{assessment.version}
            </span>
          </div>
          <div className="flex items-center gap-1 shrink-0">
            <button
              onClick={() => setExpanded((e) => !e)}
              className="text-slate-500 hover:text-slate-300 transition-colors p-0.5"
              aria-label={
                expanded ? "Collapse assessment" : "Expand assessment"
              }
            >
              {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            </button>
            {onDismiss && (
              <button
                onClick={onDismiss}
                className="text-slate-600 hover:text-slate-400 transition-colors text-xs px-1"
                aria-label="Dismiss assessment"
              >
                ✕
              </button>
            )}
          </div>
        </div>

        {/* Conclusion */}
        <p className="text-sm font-semibold text-slate-100 leading-snug mb-2">
          {assessment.conclusion}
        </p>

        {/* Confidence band */}
        <div className="space-y-0.5">
          <div className="flex items-center justify-between">
            <span className="text-[10px] text-slate-500 uppercase tracking-wider">
              Confidence
            </span>
            <span className="text-[10px] text-slate-400">
              {lowPct}%–{highPct}%
            </span>
          </div>
          <ConfidenceBar value={confidence.mid} />
          <p className="text-[10px] text-slate-500">
            Mid-point estimate: {midPct}%
          </p>
        </div>
      </div>

      {/* ── Expandable Detail ──────────────────────────────────────────────── */}
      {expanded && (
        <div className="border-t border-slate-700 px-4 py-3 space-y-3 text-xs">
          {/* Reasoning */}
          {assessment.reasoning && (
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 mb-1">
                Reasoning
              </p>
              <p className="text-slate-300 leading-relaxed">
                {assessment.reasoning}
              </p>
            </div>
          )}

          {/* Assumptions */}
          {assessment.assumptions.length > 0 && (
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 mb-1">
                Assumptions
              </p>
              <ul className="space-y-0.5">
                {assessment.assumptions.map((a, i) => (
                  <li key={i} className="flex gap-1.5 text-slate-300">
                    <CircleDot
                      size={10}
                      className="mt-0.5 shrink-0 text-slate-600"
                    />
                    {a}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Evidence summary */}
          <div className="flex gap-3">
            <div className="flex items-center gap-1.5">
              <ShieldCheck size={12} className="text-emerald-500" />
              <span className="text-slate-300">
                <span className="font-semibold text-emerald-400">
                  {supportCount}
                </span>{" "}
                supporting
              </span>
            </div>
            <div className="flex items-center gap-1.5">
              <AlertTriangle size={12} className="text-amber-500" />
              <span className="text-slate-300">
                <span className="font-semibold text-amber-400">
                  {contradictCount}
                </span>{" "}
                contradicting
              </span>
            </div>
          </div>

          {/* Intelligence gaps */}
          {gapCount > 0 && (
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 mb-1">
                Intelligence Gaps ({gapCount})
              </p>
              <ul className="space-y-0.5">
                {assessment.collection_gaps.map((gap, i) => (
                  <li key={i} className="flex gap-1.5 text-slate-400">
                    <ChevronRight
                      size={10}
                      className="mt-0.5 shrink-0 text-slate-600"
                    />
                    {gap}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Recommended next actions */}
          {assessment.recommended_next_actions.length > 0 && (
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 mb-1">
                Recommended Actions
              </p>
              <ol className="space-y-0.5 list-decimal list-inside">
                {assessment.recommended_next_actions.map((action, i) => (
                  <li key={i} className="text-slate-300">
                    {action}
                  </li>
                ))}
              </ol>
            </div>
          )}

          {/* Metadata footer */}
          <div className="border-t border-slate-800 pt-2 flex items-center justify-between text-[10px] text-slate-600">
            <span>
              KIQ: <span className="font-mono">{assessment.kiq_id}</span>
            </span>
            <span>{new Date(assessment.modified).toLocaleString()}</span>
          </div>
        </div>
      )}
    </aside>
  );
}

/**
 * AssessmentEmptyState — shown in the panel area when no assessment is
 * available yet for the current query.
 */
export function AssessmentEmptyState() {
  return (
    <div
      className="flex flex-col items-center justify-center px-4 py-6 text-center bg-slate-900 border border-slate-700 rounded-lg"
      data-testid="assessment-empty-state"
    >
      <ShieldCheck size={24} className="text-slate-700 mb-2" />
      <p className="text-xs text-slate-500">No assessment yet</p>
      <p className="text-[10px] text-slate-600 mt-0.5">
        An assessment will appear here once the Processor evaluates a KIQ-tagged
        event.
      </p>
    </div>
  );
}
