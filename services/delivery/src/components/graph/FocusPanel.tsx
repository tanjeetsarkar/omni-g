"use client";

/**
 * FocusPanel — slide-in sidebar showing selected node details (M5.2).
 *
 * Props:
 *   nodeId:  ID of the selected node (null → shows placeholder)
 *   nodes:   full node list to look up details
 *   onClose: callback to deselect the node
 */

import type { GraphNode } from "@/types/graph";

interface FocusPanelProps {
  nodeId: string | null;
  nodes: GraphNode[];
  onClose: () => void;
}

const STIX_BADGE_COLORS: Record<string, string> = {
  "threat-actor": "bg-red-700 text-white",
  malware: "bg-orange-600 text-white",
  "attack-pattern": "bg-yellow-500 text-black",
  campaign: "bg-purple-600 text-white",
  identity: "bg-blue-600 text-white",
  tool: "bg-cyan-600 text-white",
  location: "bg-emerald-600 text-white",
  vulnerability: "bg-rose-600 text-white",
};

export default function FocusPanel({ nodeId, nodes, onClose }: FocusPanelProps) {
  const node = nodeId ? nodes.find((n) => n.id === nodeId) ?? null : null;

  return (
    <aside
      className="w-80 bg-slate-900 border-l border-slate-700 flex flex-col h-full overflow-y-auto"
      aria-label="Node details panel"
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-700">
        <h2 className="text-sm font-semibold text-slate-200 uppercase tracking-wide">
          Node Details
        </h2>
        <button
          onClick={onClose}
          className="text-slate-400 hover:text-slate-100 text-xl leading-none"
          aria-label="Close panel"
        >
          ×
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 p-4">
        {!node ? (
          <p className="text-slate-500 text-sm mt-4 text-center">
            Click a node to inspect
          </p>
        ) : (
          <div className="space-y-4">
            {/* Label */}
            <div>
              <p className="text-xs text-slate-500 uppercase mb-1">Entity</p>
              <p className="text-slate-100 font-semibold text-lg">{node.label}</p>
            </div>

            {/* STIX type badge */}
            {node.stixType && (
              <div>
                <p className="text-xs text-slate-500 uppercase mb-1">STIX Type</p>
                <span
                  className={`inline-block text-xs font-medium px-2 py-1 rounded ${
                    STIX_BADGE_COLORS[node.stixType] ?? "bg-slate-600 text-white"
                  }`}
                >
                  {node.stixType}
                </span>
              </div>
            )}

            {/* Confidence bar */}
            {node.confidence != null && (
              <div>
                <p className="text-xs text-slate-500 uppercase mb-1">
                  Confidence{" "}
                  <span className="text-slate-300 normal-case">
                    {(node.confidence * 100).toFixed(0)}%
                  </span>
                </p>
                <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-indigo-500 rounded-full"
                    style={{ width: `${node.confidence * 100}%` }}
                  />
                </div>
              </div>
            )}

            {/* Community summary */}
            {node.communitySummary && (
              <div>
                <p className="text-xs text-slate-500 uppercase mb-1">
                  Community Summary
                </p>
                <p className="text-slate-300 text-sm leading-relaxed">
                  {node.communitySummary}
                </p>
              </div>
            )}
          </div>
        )}
      </div>
    </aside>
  );
}
