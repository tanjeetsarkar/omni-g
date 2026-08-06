"use client";

import React from "react";
import { X, Calendar, Database, ShieldAlert, Cpu } from "lucide-react";
import type { EChartsNode } from "../canvas/EChartsGraphCanvas";

interface SourceTracePaneProps {
  selectedNode: EChartsNode | null;
  onClose: () => void;
}

export function SourceTracePane({
  selectedNode,
  onClose,
}: SourceTracePaneProps) {
  if (!selectedNode) return null;

  return (
    <div
      className="absolute top-0 right-0 h-full w-80 bg-slate-900 border-l border-slate-800 text-slate-100 shadow-2xl flex flex-col z-50 transform transition-transform duration-300 ease-in-out"
      style={{ top: "0" }}
    >
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-slate-800 shrink-0">
        <div className="flex items-center gap-2">
          <ShieldAlert size={16} className="text-indigo-400" />
          <h2 className="font-semibold text-sm">Entity Inspector</h2>
        </div>
        <button
          onClick={onClose}
          className="p-1 rounded hover:bg-slate-800 text-slate-400 hover:text-slate-200 transition-colors"
          aria-label="Close panel"
        >
          <X size={16} />
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* Name and Type */}
        <div>
          <span className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">
            {selectedNode.category}
          </span>
          <h3 className="text-lg font-bold text-slate-100 mt-2 break-words leading-snug">
            {selectedNode.name}
          </h3>
        </div>

        {/* Key-Value Details */}
        <div className="bg-slate-950/50 rounded-lg p-3 border border-slate-800/80 space-y-2.5 text-xs">
          <div className="flex items-center justify-between">
            <span className="text-slate-500 flex items-center gap-1.5">
              <Cpu size={12} />
              Relevance Score
            </span>
            <span className="font-semibold text-indigo-400">
              {Number(selectedNode.value).toFixed(4)}
            </span>
          </div>
          {selectedNode.sourceId && (
            <div className="flex items-center justify-between">
              <span className="text-slate-500 flex items-center gap-1.5">
                <Database size={12} />
                Source reference
              </span>
              <span
                className="font-medium text-slate-300 truncate max-w-[150px]"
                title={selectedNode.sourceId}
              >
                {selectedNode.sourceId}
              </span>
            </div>
          )}
          {selectedNode.timestamp && (
            <div className="flex items-center justify-between">
              <span className="text-slate-500 flex items-center gap-1.5">
                <Calendar size={12} />
                Timestamp
              </span>
              <span className="font-medium text-slate-300">
                {selectedNode.timestamp.slice(0, 19).replace("T", " ")}
              </span>
            </div>
          )}
        </div>

        {/* Source Text Context Unit Section */}
        <div className="space-y-2">
          <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
            Raw Context / Source Evidence
          </h4>
          <div className="bg-slate-950/40 rounded-lg p-3 border border-slate-800 text-xs text-slate-300 leading-relaxed font-normal whitespace-pre-wrap select-all">
            {selectedNode.rawContext ? (
              selectedNode.rawContext
            ) : (
              <span className="italic text-slate-500">
                No raw text context available for this node alignment.
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
