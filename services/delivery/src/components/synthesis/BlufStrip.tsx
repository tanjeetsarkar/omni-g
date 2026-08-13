"use client";

/**
 * BlufStrip — collapsible BLUF (Bottom Line Up Front) summary panel
 * that surfaces the "so what" from calibrated context units.
 *
 * Two modes:
 *   1. Extractive (zero-LLM): Shows top-3 context units by score as bullet points
 *   2. LLM-synthesized (optional): Calls POST /synthesize for a 2-3 sentence summary
 *
 * V4 Phase 9: Enhanced with structured SearchSummary from Processor /search.
 * Shows cache status badge, pipeline indicator, entity type pills, source badges,
 * and empty-state handling.
 *
 * Consumes the context_units array from POST /api/query, plus the summary object
 * from the Zustand store.
 */

import { useState, useCallback } from "react";
import {
  ChevronDown,
  ChevronUp,
  Sparkles,
  Loader,
  AlertCircle,
  Zap,
  Database,
  Radio,
  Server,
  Circle,
} from "lucide-react";
import type { ContextUnit, SearchSummary } from "@/types/entities";

interface BlufStripProps {
  contextUnits: ContextUnit[];
  query?: string;
  tenantId?: string;
  /** V4 Phase 9: structured summary from the /api/query response. */
  summary?: SearchSummary | null;
}

export function BlufStrip({
  contextUnits,
  query,
  tenantId,
  summary,
}: BlufStripProps) {
  const [collapsed, setCollapsed] = useState(false);
  const [llmSummary, setLlmSummary] = useState<string | null>(null);
  const [synthesizing, setSynthesizing] = useState(false);
  const [synthesisError, setSynthesisError] = useState<string | null>(null);

  // Sort by score descending, take top 3
  const topContextUnits = [...contextUnits]
    .sort((a, b) => b.score - a.score)
    .slice(0, 3);

  const handleSynthesize = useCallback(async () => {
    if (!query || !tenantId) return;
    setSynthesizing(true);
    setSynthesisError(null);
    try {
      const res = await fetch("/api/synthesize", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query,
          tenant_id: tenantId,
          context_units: contextUnits,
        }),
      });
      if (!res.ok) throw new Error(`Synthesis failed: HTTP ${res.status}`);
      const data = await res.json();
      setLlmSummary(data.summary);
    } catch (err) {
      setSynthesisError(
        err instanceof Error ? err.message : "Synthesis unavailable",
      );
    } finally {
      setSynthesizing(false);
    }
  }, [query, tenantId, contextUnits]);

  // V4 Phase 9: empty state — no results and no pipeline running
  const showEmptyState =
    topContextUnits.length === 0 && !summary?.pipeline_running;

  // ── Empty state ───────────────────────────────────────────────────────
  if (showEmptyState) {
    return (
      <div className="border-b border-slate-800/80 bg-slate-900/50">
        <button
          onClick={() => setCollapsed(!collapsed)}
          className="w-full flex items-center gap-2 px-4 py-2 text-xs text-slate-400 hover:text-slate-200 transition-colors"
          aria-expanded={!collapsed}
        >
          <Sparkles size={14} className="text-indigo-400" />
          <span className="font-semibold text-slate-300">BLUF Summary</span>
          <div className="flex-1" />
          {collapsed ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
        </button>
      </div>
    );
  }

  // ── Pipeline running indicator ───────────────────────────────────────
  if (summary?.pipeline_running && topContextUnits.length === 0) {
    return (
      <div className="border-b border-slate-800/80 bg-slate-900/50">
        <div className="px-4 py-3 flex items-center gap-3">
          <div className="flex items-center gap-1.5">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-indigo-400 opacity-75" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-indigo-500" />
            </span>
            <span className="text-xs text-indigo-400 font-medium">
              Pipeline enriching results
            </span>
          </div>
          <span className="text-xs text-slate-500">
            <span className="animate-pulse">···</span>
          </span>
        </div>
      </div>
    );
  }

  return (
    <div className="border-b border-slate-800/80 bg-slate-900/50">
      {/* Header bar */}
      <button
        onClick={() => setCollapsed(!collapsed)}
        className="w-full flex items-center gap-2 px-4 py-2 text-xs text-slate-400 hover:text-slate-200 transition-colors"
        aria-expanded={!collapsed}
      >
        <Sparkles size={14} className="text-indigo-400" />
        <span className="font-semibold text-slate-300">BLUF Summary</span>
        {summary && (
          <>
            {/* Entity count */}
            <span className="text-slate-500 font-mono">
              {summary.total_entities} entities
            </span>
            {/* Cache badge */}
            {summary.cached && (
              <span className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded-full bg-emerald-950/50 border border-emerald-800/40 text-emerald-400">
                <Zap size={10} />
                Instant (cache)
              </span>
            )}
            {/* Pipeline running badge */}
            {summary.pipeline_running && (
              <span className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded-full bg-indigo-950/50 border border-indigo-800/40 text-indigo-400">
                <span className="relative flex h-1.5 w-1.5">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-indigo-400 opacity-75" />
                  <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-indigo-500" />
                </span>
                Enriching
              </span>
            )}
          </>
        )}
        {topContextUnits.length > 0 && (
          <span className="text-slate-600">
            ({topContextUnits.length} key finding
            {topContextUnits.length > 1 ? "s" : ""})
          </span>
        )}
        <div className="flex-1" />
        {collapsed ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
      </button>

      {!collapsed && (
        <div className="px-4 pb-3 space-y-2">
          {/* V4 Phase 9: Entity type + source summary pills */}
          {summary && (
            <div className="flex flex-wrap items-center gap-2">
              {/* Entity type breakdown */}
              {Object.entries(summary.entity_types)
                .sort(([, a], [, b]) => b - a)
                .map(([type, count]) => (
                  <span
                    key={type}
                    className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded-full bg-slate-800 border border-slate-700 text-slate-300"
                  >
                    <Database size={10} className="text-slate-500" />
                    {count} {type}
                  </span>
                ))}
              {/* Source badges */}
              {summary.sources.slice(0, 4).map((src) => (
                <span
                  key={src}
                  className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded-full bg-purple-950/30 border border-purple-800/30 text-purple-300"
                >
                  <Radio size={10} />
                  {src}
                </span>
              ))}
            </div>
          )}

          {/* V4 Phase 9: Pipeline enriching indicator (when running + has results) */}
          {summary?.pipeline_running && (
            <div className="flex items-center gap-2 text-xs text-indigo-400">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-indigo-400 opacity-75" />
                <span className="relative inline-flex rounded-full h-2 w-2 bg-indigo-500" />
              </span>
              <span className="font-medium">Pipeline enriching results</span>
              <span className="text-slate-500">
                <span className="animate-pulse">···</span>
              </span>
            </div>
          )}

          {/* LLM-synthesized summary (if available) */}
          {llmSummary && (
            <div className="bg-indigo-950/30 border border-indigo-800/40 rounded-lg p-3">
              <p className="text-sm text-slate-200 leading-relaxed">
                {llmSummary}
              </p>
            </div>
          )}

          {/* Extractive context units */}
          {topContextUnits.length > 0 && (
            <div className="space-y-1.5">
              {topContextUnits.map((cu, i) => (
                <div
                  key={cu.context_id}
                  className="flex items-start gap-2 text-xs text-slate-400"
                >
                  <span className="flex-shrink-0 w-4 h-4 rounded-full bg-indigo-900/50 text-indigo-300 flex items-center justify-center text-[10px] font-bold mt-0.5">
                    {i + 1}
                  </span>
                  <div className="flex-1 min-w-0">
                    <p className="text-slate-300 leading-relaxed line-clamp-2">
                      {cu.text}
                    </p>
                    <div className="flex items-center gap-2 mt-0.5">
                      <span className="text-[10px] text-slate-500">
                        Score: {(cu.score * 100).toFixed(0)}%
                      </span>
                      {cu.entity_ids && cu.entity_ids.length > 0 && (
                        <span className="text-[10px] text-slate-500">
                          {cu.entity_ids.length} entit
                          {cu.entity_ids.length > 1 ? "ies" : "y"}
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* V4 Phase 9: Top entities by degree */}
          {summary && summary.top_entities.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-[10px] text-slate-500 font-semibold">
                Top entities:
              </span>
              {summary.top_entities.map((e) => (
                <span
                  key={`${e.name}-${e.type}`}
                  className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded bg-slate-800/70 border border-slate-700/50 text-slate-300"
                >
                  <Circle size={6} className="text-slate-500" />
                  {e.name}
                  <span className="text-slate-600">({e.type})</span>
                  <span className="text-slate-500 ml-0.5">{e.degree}</span>
                </span>
              ))}
            </div>
          )}

          {/* LLM synthesis button */}
          {!llmSummary && query && tenantId && (
            <button
              onClick={handleSynthesize}
              disabled={synthesizing}
              className="flex items-center gap-1.5 text-xs text-indigo-400 hover:text-indigo-300 disabled:text-slate-600 transition-colors"
            >
              {synthesizing ? (
                <Loader size={12} className="animate-spin" />
              ) : (
                <Sparkles size={12} />
              )}
              {synthesizing ? "Synthesizing…" : "Generate AI summary"}
            </button>
          )}

          {synthesisError && (
            <div className="flex items-center gap-1.5 text-xs text-amber-400">
              <AlertCircle size={12} />
              <span>{synthesisError}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
