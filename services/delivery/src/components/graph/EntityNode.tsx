"use client";
import React, { useState } from "react";
import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import { clsx } from "clsx";
import type { Entity } from "../../types/entities";

const TYPE_COLORS: Record<string, string> = {
  Person: "bg-blue-500",
  Organization: "bg-purple-500",
  Event: "bg-orange-500",
  Location: "bg-green-500",
  Topic: "bg-yellow-500",
  Concept: "bg-pink-500",
  Unknown: "bg-gray-500",
};

function getTypeColor(type: string): string {
  return TYPE_COLORS[type] ?? "bg-indigo-500";
}

// EntityData must satisfy Record<string,unknown> for React Flow's Node generic
type EntityData = Entity & Record<string, unknown>;
export type EntityNodeType = Node<EntityData, "entity">;

export function EntityNode({ data, selected }: NodeProps<EntityNodeType>) {
  const [expanded, setExpanded] = useState(false);

  const confidencePct = Math.round((data.confidence ?? 0) * 100);
  const confidenceColor =
    confidencePct >= 80
      ? "bg-green-500"
      : confidencePct >= 50
        ? "bg-yellow-500"
        : "bg-red-500";

  const propertyEntries = Object.entries(data.properties ?? {});

  return (
    <div
      className={clsx(
        "min-w-[180px] max-w-[280px] rounded-lg border text-xs shadow-md bg-slate-800 text-slate-100 cursor-pointer select-none",
        selected
          ? "border-indigo-400 ring-2 ring-indigo-400/50"
          : "border-slate-600 hover:border-slate-400",
      )}
      onClick={() => setExpanded((v) => !v)}
      role="button"
      aria-expanded={expanded}
    >
      <Handle type="target" position={Position.Top} className="!bg-slate-500" />

      {/* Header: type badge + name */}
      <div className="flex items-center gap-2 px-3 py-2">
        <span
          className={clsx(
            "shrink-0 px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wide text-white",
            getTypeColor(data.type ?? "Unknown"),
          )}
        >
          {data.type ?? "Unknown"}
        </span>
        <span className="font-medium truncate leading-tight">{data.name}</span>
      </div>

      {/* Confidence bar */}
      <div className="px-3 pb-2">
        <div className="flex items-center gap-2">
          <div className="flex-1 h-1.5 rounded-full bg-slate-700 overflow-hidden">
            <div
              className={clsx(
                "h-full rounded-full transition-all",
                confidenceColor,
              )}
              style={{ width: `${confidencePct}%` }}
            />
          </div>
          <span className="text-slate-400 tabular-nums w-7 text-right">
            {confidencePct}%
          </span>
        </div>
      </div>

      {/* Expandable accordion: description + properties */}
      {expanded && (
        <div className="border-t border-slate-700 px-3 py-2 space-y-2">
          {data.description && (
            <p className="text-slate-300 leading-relaxed whitespace-pre-wrap break-words">
              {data.description}
            </p>
          )}
          {propertyEntries.length > 0 && (
            <dl className="grid grid-cols-[auto_1fr] gap-x-2 gap-y-0.5">
              {propertyEntries.map(([k, v]) => (
                <React.Fragment key={k}>
                  <dt className="text-slate-500 font-medium truncate">{k}</dt>
                  <dd className="text-slate-300 truncate">
                    {typeof v === "object" ? JSON.stringify(v) : String(v)}
                  </dd>
                </React.Fragment>
              ))}
            </dl>
          )}
          {!data.description && propertyEntries.length === 0 && (
            <p className="text-slate-500 italic">No additional details.</p>
          )}
          <div className="flex items-center gap-2 text-[10px] text-slate-500 pt-1 border-t border-slate-700/50">
            {data.source_id && <span>src: {data.source_id}</span>}
            <span className="ml-auto">{data.created?.slice(0, 10)}</span>
          </div>
        </div>
      )}

      <Handle
        type="source"
        position={Position.Bottom}
        className="!bg-slate-500"
      />
    </div>
  );
}
