"use client";

import React, { useState } from "react";
import { Settings, X } from "lucide-react";
import { useGraphExplorerStore } from "../../store/useGraphExplorerStore";

/**
 * V4 Track 1: top-right floating settings gear popover.
 *
 * Exposes three tuning dials that map directly onto the Processor query
 * contract:
 * - Relevance Threshold (τ ∈ [0.1, 1.0]) — edges below τ are pruned
 * - Traversal Depth (D_max ∈ [1, 4]) — multi-hop expansion limit
 * - Token Cap (L_max ∈ [2048, 8192]) — calibrated context budget
 *
 * Changing any dial updates the Zustand store; the next `executeQuery` call
 * forwards the new values to /api/query.
 */
export function SettingsGearPanel() {
  const [open, setOpen] = useState(false);
  const depth = useGraphExplorerStore((s) => s.depth);
  const threshold = useGraphExplorerStore((s) => s.relevanceThreshold);
  const tokenCap = useGraphExplorerStore((s) => s.tokenCap);
  const setSettings = useGraphExplorerStore((s) => s.setSettings);

  return (
    <div className="absolute top-4 right-4 z-40">
      <button
        onClick={() => setOpen((v) => !v)}
        className="p-2 rounded-full shadow-2xl backdrop-blur-md bg-background/70 border border-slate-700/60 text-slate-300 hover:text-slate-100 hover:border-indigo-400/60 transition-colors"
        aria-label="Graph settings"
        aria-expanded={open}
      >
        <Settings size={18} className={open ? "text-indigo-400" : undefined} />
      </button>

      {open && (
        <div className="absolute top-12 right-0 w-72 rounded-xl shadow-2xl backdrop-blur-md bg-background/90 border border-slate-700/60 p-4 space-y-4 text-slate-200">
          <div className="flex items-center justify-between">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400">
              Graph Settings
            </h3>
            <button
              onClick={() => setOpen(false)}
              className="text-slate-500 hover:text-slate-200"
              aria-label="Close settings"
            >
              <X size={14} />
            </button>
          </div>

          {/* Relevance Threshold (τ) */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between text-xs">
              <label htmlFor="threshold" className="text-slate-400">
                Relevance Threshold (τ)
              </label>
              <span className="font-mono text-indigo-300">
                {threshold.toFixed(2)}
              </span>
            </div>
            <input
              id="threshold"
              type="range"
              min={0.1}
              max={1.0}
              step={0.05}
              value={threshold}
              onChange={(e) =>
                setSettings(depth, parseFloat(e.target.value), tokenCap)
              }
              className="w-full accent-indigo-500"
            />
          </div>

          {/* Traversal Depth (D_max) */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between text-xs">
              <label htmlFor="depth" className="text-slate-400">
                Traversal Depth (D_max)
              </label>
              <span className="font-mono text-indigo-300">{depth}</span>
            </div>
            <div className="flex gap-1">
              {[1, 2, 3, 4].map((d) => (
                <button
                  key={d}
                  onClick={() => setSettings(d, threshold, tokenCap)}
                  className={`flex-1 py-1 rounded text-xs font-medium transition-colors ${
                    depth === d
                      ? "bg-indigo-500 text-white"
                      : "bg-slate-800 text-slate-400 hover:bg-slate-700"
                  }`}
                >
                  {d}
                </button>
              ))}
            </div>
          </div>

          {/* Token Cap (L_max) */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between text-xs">
              <label htmlFor="tokencap" className="text-slate-400">
                Token Cap (L max)
              </label>
              <span className="font-mono text-indigo-300">{tokenCap}</span>
            </div>
            <input
              id="tokencap"
              type="range"
              min={2048}
              max={8192}
              step={512}
              value={tokenCap}
              onChange={(e) =>
                setSettings(depth, threshold, parseInt(e.target.value, 10))
              }
              className="w-full accent-indigo-500"
            />
          </div>
        </div>
      )}
    </div>
  );
}
