"use client";

/**
 * BlufStrip — collapsible BLUF (Bottom Line Up Front) summary panel
 * that surfaces the "so what" from calibrated context units.
 *
 * Two modes:
 *   1. Extractive (zero-LLM): Shows top-3 context units by score as bullet points
 *   2. LLM-synthesized (optional): Calls POST /synthesize for a 2-3 sentence summary
 *
 * Consumes the context_units array already returned by POST /api/query.
 */

import { useState, useCallback } from "react";
import {
  ChevronDown,
  ChevronUp,
  Sparkles,
  Loader,
  AlertCircle,
} from "lucide-react";
import type { ContextUnit } from "@/types/entities";

interface BlufStripProps {
  contextUnits: ContextUnit[];
  query?: string;
  tenantId?: string;
}

export function BlufStrip({ contextUnits, query, tenantId }: BlufStripProps) {
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

  if (topContextUnits.length === 0) return null;

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
        <span className="text-slate-600">
          ({topContextUnits.length} key finding
          {topContextUnits.length > 1 ? "s" : ""})
        </span>
        <div className="flex-1" />
        {collapsed ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
      </button>

      {!collapsed && (
        <div className="px-4 pb-3 space-y-2">
          {/* LLM-synthesized summary (if available) */}
          {llmSummary && (
            <div className="bg-indigo-950/30 border border-indigo-800/40 rounded-lg p-3">
              <p className="text-sm text-slate-200 leading-relaxed">
                {llmSummary}
              </p>
            </div>
          )}

          {/* Extractive context units */}
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
