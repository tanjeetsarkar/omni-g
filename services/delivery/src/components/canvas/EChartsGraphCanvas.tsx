"use client";

import React from "react";
import ReactECharts from "echarts-for-react";

export interface EChartsNode {
  id: string;
  name: string;
  label?: string; // Human-readable node label
  symbolSize: number;
  category: string;
  value: number;
  itemStyle: { color: string };
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

export function EChartsGraphCanvas({
  nodes,
  links,
  onNodeSelect,
  onNodeDrillDown,
}: EChartsGraphCanvasProps) {
  // Dynamically extract unique categories present in the rendered nodes to build a robust legend
  const uniqueCategories = Array.from(
    new Set(nodes.map((n) => n.category).filter(Boolean)),
  ).sort();

  const seriesCategories = uniqueCategories.map((cat) => ({
    name: cat,
  }));

  const option = {
    backgroundColor: "transparent",
    tooltip: {
      trigger: "item",
      formatter: (params: unknown) => {
        const p = params as EChartsFormatterParams;
        if (p.dataType === "node") {
          const displayLabel = p.data.label || p.data.name;
          return `${displayLabel} [${p.data.category}]<br/>Score: ${Number(p.data.value).toFixed(2)}`;
        }
        return `${p.data.source} → ${p.data.target}<br/>Weight: ${Number(p.data.value).toFixed(2)}`;
      },
      backgroundColor: "#1e293b",
      borderColor: "#475569",
      textStyle: { color: "#f8fafc" },
    },
    legend: [
      {
        data: uniqueCategories,
        textStyle: { color: "#94a3b8" },
      },
    ],
    series: [
      {
        type: "graph",
        layout: "force",
        data: nodes,
        links: links,
        categories: seriesCategories,
        roam: true,
        label: {
          show: true,
          position: "right",
          formatter: (params: any) => params.data.label || params.name,
          color: "#cbd5e1",
          fontSize: 10,
        },
        force: {
          repulsion: 250,
          gravity: 0.1,
          edgeLength: 90,
          friction: 0.6,
        },
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
    <ReactECharts
      option={option}
      onEvents={onEvents}
      style={{ height: "100%", width: "100%" }}
    />
  );
}
