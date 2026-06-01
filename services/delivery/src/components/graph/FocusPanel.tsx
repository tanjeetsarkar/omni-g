"use client";

/**
 * FocusPanel — dual-tab slide-in sidebar (M6 UX).
 *
 * Tab 1 — Entity Dossier: STIX type, confidence, community summary.
 * Tab 2 — Audio Briefings: embedded BriefingPanel for Kokoro TTS playback.
 *
 * Props:
 *   nodeId:   ID of the selected node (null → shows placeholder)
 *   nodes:    full node list to look up details
 *   tenantId: tenant scope forwarded to BriefingPanel
 *   onClose:  callback to deselect the node
 */

import { useState } from "react";
import { BookOpen, Volume2 } from "lucide-react";

import BriefingPanel from "@/components/briefing/BriefingPanel";
import type { GraphNode } from "@/types/graph";

type TabId = "entity" | "briefings";

const TABS: { id: TabId; label: string; Icon: typeof BookOpen }[] = [
  { id: "entity", label: "Entity", Icon: BookOpen },
  { id: "briefings", label: "Briefings", Icon: Volume2 },
];

interface FocusPanelProps {
  nodeId: string | null;
  nodes: GraphNode[];
  tenantId: string;
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

export default function FocusPanel({
  nodeId,
  nodes,
  tenantId,
  onClose,
}: FocusPanelProps) {
  const [activeTab, setActiveTab] = useState<TabId>("entity");
  const node = nodeId ? (nodes.find((n) => n.id === nodeId) ?? null) : null;

  return (
    <aside
      className="w-80 bg-slate-900 border-l border-slate-700 flex flex-col h-full"
      aria-label="Entity details panel"
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-700 shrink-0">
        <h2 className="text-sm font-semibold text-slate-200 uppercase tracking-wide">
          Intelligence Panel
        </h2>
        <button
          onClick={onClose}
          className="text-slate-400 hover:text-slate-100 text-xl leading-none"
          aria-label="Close panel"
        >
          ×
        </button>
      </div>

      {/* Tab bar */}
      <div className="flex border-b border-slate-700 shrink-0" role="tablist">
        {TABS.map(({ id, label, Icon }) => (
          <button
            key={id}
            role="tab"
            aria-selected={activeTab === id}
            onClick={() => setActiveTab(id)}
            className={`flex-1 flex items-center justify-center gap-1.5 py-2.5 text-xs font-medium transition-colors ${
              activeTab === id
                ? "text-indigo-400 border-b-2 border-indigo-500"
                : "text-slate-500 hover:text-slate-300 border-b-2 border-transparent"
            }`}
          >
            <Icon size={12} />
            {label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-y-auto">
        {/* Tab 1 — Entity Dossier */}
        {activeTab === "entity" && (
          <div className="p-4">
            {!node ? (
              <p className="text-slate-500 text-sm mt-6 text-center">
                Click a node to inspect
              </p>
            ) : (
              <div className="space-y-5">
                <div>
                  <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">
                    Entity
                  </p>
                  <p className="text-slate-100 font-bold text-base leading-snug break-words">
                    {node.label}
                  </p>
                </div>

                {node.stixType && (
                  <div>
                    <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-1.5">
                      STIX Type
                    </p>
                    <span
                      className={`inline-block text-xs font-semibold px-2.5 py-1 rounded-full ${
                        STIX_BADGE_COLORS[node.stixType] ??
                        "bg-slate-600 text-white"
                      }`}
                    >
                      {node.stixType}
                    </span>
                  </div>
                )}

                {node.confidence != null && (
                  <div>
                    <div className="flex justify-between text-[10px] text-slate-500 mb-1.5">
                      <span className="uppercase tracking-wider">
                        Confidence
                      </span>
                      <span className="text-slate-300 font-mono">
                        {(node.confidence * 100).toFixed(0)}%
                      </span>
                    </div>
                    <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
                      <div
                        className="h-full rounded-full transition-all"
                        style={{
                          width: `${node.confidence * 100}%`,
                          backgroundColor:
                            node.confidence >= 0.8
                              ? "#6366f1"
                              : node.confidence >= 0.5
                                ? "#f59e0b"
                                : "#ef4444",
                        }}
                      />
                    </div>
                    <p className="text-[10px] text-slate-600 mt-1">
                      {node.confidence >= 0.8
                        ? "High — auto-merged"
                        : node.confidence >= 0.5
                          ? "Moderate — analyst review recommended"
                          : "Low — treat as preliminary signal"}
                    </p>
                  </div>
                )}

                {node.communitySummary && (
                  <div>
                    <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-1.5">
                      Community Summary
                    </p>
                    <p className="text-slate-300 text-xs leading-relaxed">
                      {node.communitySummary}
                    </p>
                  </div>
                )}

                {node.communityId && (
                  <div>
                    <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">
                      Community ID
                    </p>
                    <p className="text-slate-500 text-[10px] font-mono break-all">
                      {node.communityId}
                    </p>
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* Tab 2 — Audio Briefings */}
        {activeTab === "briefings" && (
          <div className="p-4">
            <BriefingPanel tenantId={tenantId} />
          </div>
        )}
      </div>
    </aside>
  );
}
