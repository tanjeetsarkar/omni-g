"use client";

import React, { useState, useEffect, useCallback } from "react";
import ReactECharts from "echarts-for-react";
import {
  formatConfidenceBar,
  RICH_LABEL_STYLES,
} from "./useEChartsGraphAdapter";

export interface EChartsNode {
  id: string;
  name: string;
  label?: string; // Human-readable node label
  symbol?: string;
  symbolSize: number | number[];
  category: string;
  value: number;
  x?: number;
  y?: number;
  collapsed?: boolean;
  itemStyle: {
    color: string;
    opacity?: number;
    borderColor?: string;
    borderWidth?: number;
    borderRadius?: number;
  };
  labelEnabled?: boolean;
  confidence?: number;
  rawContext?: string;
  sourceId?: string;
  sourceName?: string;
  sourceUrl?: string;
  pluginName?: string;
  subEntityCount?: number;
  timestamp?: string;
}

export interface EChartsLink {
  source: string;
  target: string;
  value: number;
  lineStyle?: { width: number; opacity: number };
}

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
    sourceName?: string;
    pluginName?: string;
    subEntityCount?: number;
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
    name?: string;
    collapsed?: boolean;
  };
}

interface EChartsGraphCanvasProps {
  nodes: EChartsNode[];
  links: EChartsLink[];
  treeData?: Record<string, unknown> | null;
  onNodeSelect: (node: EChartsNode) => void;
  onNodeDrillDown: (nodeId: string) => void;
}

export function EChartsGraphCanvas({
  nodes,
  links,
  treeData,
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

  const seriesCategories = uniqueCategories.map((cat) => ({
    name: cat,
  }));

  const option = {
    backgroundColor: "transparent",
    tooltip: {
      trigger: "item",
      formatter: (params: unknown) => {
        const p = params as EChartsFormatterParams;
        if (p.dataType === "node" || p.dataType === "treeNode") {
          const displayLabel = p.data.label || p.data.name;
          const conf = p.data.confidence ?? p.data.value ?? 0;
          const confBar = formatConfidenceBar(conf);
          const sourceBadge = (p.data as Record<string, unknown>).sourceName
            ? ` 📍 ${(p.data as Record<string, unknown>).sourceName}`
            : "";
          const pluginIcon = (p.data as Record<string, unknown>).pluginName
            ? ` 🔌 ${(p.data as Record<string, unknown>).pluginName}`
            : "";
          const subCount =
            (p.data as Record<string, unknown>).subEntityCount ?? 0;
          const cat = p.data.category ?? "Unknown";
          return [
            `${displayLabel} [${cat}]`,
            `Confidence: ${confBar} ${(conf * 100).toFixed(0)}%`,
            `Links: ${subCount}${sourceBadge}${pluginIcon}`,
          ].join("<br/>");
        }
        // Tree edges: p.data is the child node, not {source, target}.
        // Show a meaningful transition label instead of "undefined → undefined".
        if (p.dataType === "edge" || (!p.dataType && p.data?.name)) {
          const childName = p.data?.label || p.data?.name || "?";
          const weight = p.data?.value ?? 0;
          return `→ ${childName}<br/>Weight: ${Number(weight).toFixed(2)}`;
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
        type: "tree",
        data: treeData ? [treeData] : [],
        layout: "radial",
        symbol: "circle",
        symbolSize: 12,
        roam: true,
        expandAndCollapse: true,
        initialTreeDepth: 3,
        animationDuration: 500,
        animationDurationUpdate: 300,
        label: {
          show: true,
          position: "right",
          formatter: (params: any) => {
            if (params.data.labelEnabled === false) return "";
            return params.data.label || params.name;
          },
          color: "#F8FAFC",
          fontSize: 12,
          rich: RICH_LABEL_STYLES,
        },
        emphasis: {
          focus: "descendant",
          lineStyle: {
            width: 4,
          },
        },
        lineStyle: {
          color: "#475569",
          curveness: 0.3,
        },
      },
    ],
  };

  const onEvents = {
    click: (params: unknown) => {
      const p = params as Record<string, unknown>;
      // ECharts tree series uses 'treeNode' as seriesType, not 'node' as dataType.
      // The node data is nested under p.data for tree clicks.
      const nodeData = (p.data ?? p) as Record<string, unknown>;
      const nodeId = nodeData.id ?? nodeData.name;
      if (nodeId && typeof nodeId === "string") {
        // Build an EChartsNode-compatible object from the tree node data
        const echartsNode: EChartsNode = {
          id: nodeId,
          name: (nodeData.name as string) ?? "",
          label: (nodeData.label as string) ?? (nodeData.name as string) ?? "",
          category:
            (nodeData.category as string) ??
            (nodeData.entity_type as string) ??
            "Unknown",
          symbolSize: (nodeData.symbolSize as number) ?? 12,
          value:
            (nodeData.value as number) ??
            (nodeData.confidence_score as number) ??
            0.5,
          itemStyle: (nodeData.itemStyle as EChartsNode["itemStyle"]) ?? {
            color: "#6366f1",
          },
          confidence:
            (nodeData.confidence as number) ??
            (nodeData.confidence_score as number),
          sourceName:
            (nodeData.sourceName as string) ?? (nodeData.source_name as string),
          sourceUrl:
            (nodeData.sourceUrl as string) ?? (nodeData.source_url as string),
          pluginName:
            (nodeData.pluginName as string) ?? (nodeData.plugin_name as string),
          subEntityCount:
            (nodeData.subEntityCount as number) ??
            (nodeData.sub_entity_count as number),
          rawContext:
            (nodeData.rawContext as string) ?? (nodeData.raw_context as string),
          sourceId:
            (nodeData.sourceId as string) ?? (nodeData.source_id as string),
          timestamp:
            (nodeData.timestamp as string) ?? (nodeData.ingested_at as string),
        };
        onNodeSelect(echartsNode);
      }
    },
    dblclick: (params: unknown) => {
      const p = params as EChartsDblClickParams;
      if (p.dataType === "node") {
        // Toggle expand/collapse on double-click (expandAndCollapse handles this
        // visually), and also trigger drilldown for dynamic expansion.
        onNodeDrillDown(p.data.id);
      }
    },
  };

  return (
    <div className="relative w-full h-full">
      <ReactECharts
        option={option}
        onEvents={onEvents}
        style={{ height: "100%", width: "100%" }}
      />
    </div>
  );
}
