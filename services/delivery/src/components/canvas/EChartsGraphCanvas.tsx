"use client";

import React, { useState, useEffect, useCallback } from "react";
import ReactECharts from "echarts-for-react";
import { formatConfidenceBar } from "./useEChartsGraphAdapter";

export interface EChartsNode {
  id: string;
  name: string;
  label?: string; // Human-readable node label
  symbolSize: number;
  category: string;
  value: number;
  itemStyle: {
    color: string;
    opacity?: number;
    borderColor?: string;
    borderWidth?: number;
  };
  labelEnabled?: boolean;
  confidence?: number;
  rawContext?: string;
  sourceId?: string;
  timestamp?: string;
}

export interface EChartsLink {
  source: string;
  target: string;
  value: number;
  lineStyle?: { width: number; opacity: number };
}

export type LayoutType = "force" | "circular" | "none";

interface EChartsFormatterParams {
  dataType?: string;
  name?: string;
  category?: string;
  value?: number;
  source?: string;
  target?: string;
  data: {
    name?: string;
    label?: string;
    category?: string;
    value?: number;
    confidence?: number;
    source?: string;
    target?: string;
  };
}

interface EChartsClickParams {
  dataType?: string;
  data: EChartsNode;
}

interface EChartsDblClickParams {
  dataType?: string;
  data: {
    id: string;
  };
}

interface EChartsGraphCanvasProps {
  nodes: EChartsNode[];
  links: EChartsLink[];
  onNodeSelect: (node: EChartsNode) => void;
  onNodeDrillDown: (nodeId: string) => void;
}

const LAYOUT_STORAGE_KEY = "omni-g-layout-type";

function loadLayoutPreference(): LayoutType {
  if (typeof window === "undefined") return "force";
  const saved = sessionStorage.getItem(LAYOUT_STORAGE_KEY);
  return saved === "circular" || saved === "none" ? saved : "force";
}

export function EChartsGraphCanvas({
  nodes,
  links,
  onNodeSelect,
  onNodeDrillDown,
}: EChartsGraphCanvasProps) {
  // ── B2: Legend-as-filter ──────────────────────────────────────────────────
  const uniqueCategories = Array.from(
    new Set(nodes.map((n) => n.category).filter(Boolean)),
  ).sort();

  const countMap: Record<string, number> = {};
  for (const cat of uniqueCategories) {
    countMap[cat] = nodes.filter((n) => n.category === cat).length;
  }

  // Legend selection state — default all selected
  const [selectedCategories, setSelectedCategories] = useState<
    Record<string, boolean>
  >({});

  // Reset legend selection when categories change
  useEffect(() => {
    setSelectedCategories((prev) => {
      const next: Record<string, boolean> = {};
      for (const cat of uniqueCategories) {
        next[cat] = prev[cat] ?? true;
      }
      return next;
    });
  }, [uniqueCategories.join(",")]);

  // ── B5: Layout switcher ───────────────────────────────────────────────────
  const [layoutType, setLayoutType] =
    useState<LayoutType>(loadLayoutPreference);

  // Persist layout selection
  useEffect(() => {
    if (typeof window !== "undefined") {
      sessionStorage.setItem(LAYOUT_STORAGE_KEY, layoutType);
    }
  }, [layoutType]);

  const handleLayoutChange = useCallback((layout: LayoutType) => {
    setLayoutType(layout);
  }, []);

  const seriesCategories = uniqueCategories.map((cat) => ({
    name: cat,
  }));

  // Filter nodes and links based on legend selection
  const visibleNodes = nodes.filter(
    (n) => selectedCategories[n.category] !== false,
  );
  const visibleNodeIds = new Set(visibleNodes.map((n) => n.id));
  const visibleLinks = links.filter(
    (l) =>
      visibleNodeIds.has(String(l.source)) &&
      visibleNodeIds.has(String(l.target)),
  );

  const option = {
    backgroundColor: "transparent",
    tooltip: {
      trigger: "item",
      formatter: (params: unknown) => {
        const p = params as EChartsFormatterParams;
        if (p.dataType === "node") {
          const displayLabel = p.data.label || p.data.name;
          const conf = p.data.confidence ?? p.data.value ?? 0;
          // ── B3: Confidence shown as visual bar ──
          const confBar = formatConfidenceBar(conf);
          return `${displayLabel} [${p.data.category}]<br/>Confidence: ${confBar} ${(conf * 100).toFixed(0)}%`;
        }
        return `${p.data.source} → ${p.data.target}<br/>Weight: ${Number(p.data.value).toFixed(2)}`;
      },
      backgroundColor: "#1e293b",
      borderColor: "#475569",
      textStyle: { color: "#f8fafc" },
    },
    // ── B2: Legend with counts and toggle-to-filter ──
    legend: [
      {
        data: uniqueCategories,
        selected: selectedCategories,
        selectedMode: "multiple",
        textStyle: { color: "#94a3b8" },
        formatter: (name: string) => `${name} (${countMap[name] ?? 0})`,
      },
    ],
    series: [
      {
        type: "graph",
        layout: layoutType,
        data: visibleNodes,
        links: visibleLinks,
        categories: seriesCategories,
        roam: true,
        // ── B3: Conditional label visibility per node ──
        label: {
          show: true,
          position: "right",
          formatter: (params: any) => {
            // Only show labels for nodes with confidence > 0.3
            if (params.data.labelEnabled === false) return "";
            return params.data.label || params.name;
          },
          color: "#cbd5e1",
          fontSize: 10,
        },
        ...(layoutType === "force"
          ? {
              force: {
                repulsion: 250,
                gravity: 0.1,
                edgeLength: 90,
                friction: 0.6,
              },
            }
          : layoutType === "circular"
            ? {
                circular: {
                  rotateLabel: true,
                },
              }
            : {}),
        emphasis: {
          focus: "adjacency",
          lineStyle: {
            width: 4,
          },
        },
        lineStyle: {
          color: "#475569",
          curveness: 0.1,
        },
      },
    ],
  };

  const onEvents = {
    click: (params: unknown) => {
      const p = params as EChartsClickParams;
      if (p.dataType === "node") {
        onNodeSelect(p.data);
      }
    },
    dblclick: (params: unknown) => {
      const p = params as EChartsDblClickParams;
      if (p.dataType === "node") {
        onNodeDrillDown(p.data.id);
      }
    },
  };

  return (
    <div className="relative w-full h-full">
      {/* ── B5: Layout switcher (floating top-right) ── */}
      <div className="absolute top-3 right-3 z-10 flex items-center gap-1 bg-slate-900/80 border border-slate-700 rounded-lg p-0.5 shadow-lg">
        {(["force", "circular", "none"] as LayoutType[]).map((layout) => (
          <button
            key={layout}
            onClick={() => handleLayoutChange(layout)}
            className={`px-2 py-1 text-[10px] font-medium rounded-md transition-colors ${
              layoutType === layout
                ? "bg-indigo-600 text-white"
                : "text-slate-400 hover:text-slate-200 hover:bg-slate-800"
            }`}
            title={
              layout === "force"
                ? "Force-directed layout"
                : layout === "circular"
                  ? "Circular layout"
                  : "Static layout (data positions)"
            }
          >
            {layout === "force"
              ? "Force"
              : layout === "circular"
                ? "Circular"
                : "Static"}
          </button>
        ))}
      </div>

      <ReactECharts
        option={option}
        onEvents={onEvents}
        style={{ height: "100%", width: "100%" }}
      />
    </div>
  );
}
