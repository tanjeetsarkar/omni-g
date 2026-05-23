"use client";

/**
 * FilterToolbar — compact horizontal toolbar for graph filtering.
 *
 * Provides:
 *   - Full-text search by node label
 *   - STIX-type toggle pills (coloured by type)
 *   - Confidence threshold slider
 *   - Reset button
 *   - "Showing X of Y nodes" count
 */

import React from "react";
import type { FilterState } from "@/hooks/useGraphFilter";

const STIX_COLORS: Record<string, string> = {
  "threat-actor": "#ef4444",
  malware: "#f97316",
  "attack-pattern": "#eab308",
  campaign: "#a855f7",
  identity: "#3b82f6",
  tool: "#06b6d4",
  location: "#10b981",
  vulnerability: "#f43f5e",
};

export interface FilterToolbarProps {
  availableTypes: string[];
  filterState: FilterState;
  onToggleType: (type: string) => void;
  onConfidenceChange: (v: number) => void;
  onSearchChange: (q: string) => void;
  onReset: () => void;
  shownNodes?: number;
  totalNodes?: number;
}

export default function FilterToolbar({
  availableTypes,
  filterState,
  onToggleType,
  onConfidenceChange,
  onSearchChange,
  onReset,
  shownNodes,
  totalNodes,
}: FilterToolbarProps) {
  return (
    <div className="flex items-center gap-3 px-4 py-2 bg-slate-900 border-b border-slate-700 text-sm text-slate-300 shrink-0 flex-wrap min-h-[44px]">
      {/* ── Search ─────────────────────────────────────────────────────────── */}
      <input
        type="text"
        placeholder="Search nodes…"
        value={filterState.searchQuery}
        onChange={(e) => onSearchChange(e.target.value)}
        aria-label="Search nodes"
        className="bg-slate-800 border border-slate-600 rounded px-2 py-1 text-slate-200 placeholder-slate-500 text-xs w-36 focus:outline-none focus:border-slate-400"
      />

      <span className="text-slate-700 select-none">|</span>

      {/* ── Type toggles ───────────────────────────────────────────────────── */}
      <div
        className="flex items-center gap-1 flex-wrap"
        role="group"
        aria-label="Filter by STIX type"
      >
        {availableTypes.map((type) => {
          const active = filterState.enabledTypes.has(type);
          const color = STIX_COLORS[type] ?? "#6366f1";
          return (
            <button
              key={type}
              onClick={() => onToggleType(type)}
              aria-pressed={active}
              style={{
                borderColor: color,
                color: active ? "#0f172a" : color,
                backgroundColor: active ? color : "transparent",
              }}
              className="rounded-full px-2 py-0.5 text-xs border transition-colors cursor-pointer"
            >
              {type}
            </button>
          );
        })}
      </div>

      <span className="text-slate-700 select-none">|</span>

      {/* ── Confidence slider ──────────────────────────────────────────────── */}
      <div className="flex items-center gap-2 text-xs">
        <span className="text-slate-400 shrink-0">Confidence:</span>
        <input
          type="range"
          min={0}
          max={1}
          step={0.05}
          value={filterState.minConfidence}
          onChange={(e) => onConfidenceChange(parseFloat(e.target.value))}
          aria-label="Minimum confidence"
          className="w-24 accent-indigo-500"
        />
        <span className="text-slate-300 w-8 tabular-nums">
          {filterState.minConfidence.toFixed(1)}+
        </span>
      </div>

      <span className="text-slate-700 select-none">|</span>

      {/* ── Reset ─────────────────────────────────────────────────────────── */}
      <button
        onClick={onReset}
        aria-label="Reset filters"
        className="text-xs text-slate-400 hover:text-slate-200 transition-colors px-1"
      >
        Reset
      </button>

      {/* ── Node count ────────────────────────────────────────────────────── */}
      {shownNodes !== undefined && totalNodes !== undefined && (
        <>
          <span className="text-slate-700 select-none">|</span>
          <span className="text-xs text-slate-500 shrink-0">
            Showing {shownNodes} of {totalNodes} nodes
          </span>
        </>
      )}
    </div>
  );
}
