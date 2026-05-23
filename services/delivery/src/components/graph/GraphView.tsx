"use client";

/**
 * GraphView — Sigma.js WebGL graph renderer (M5.2).
 *
 * Features:
 *   - Force-directed layout via ForceAtlas2 (50 iterations, sync)
 *   - Real-time node highlighting via highlightedNodeIds prop
 *   - Node click handler via onNodeClick prop
 *   - Performance target: 50k nodes rendered in <500ms (WebGL)
 */
import { useEffect, useRef } from "react";

import Graph from "graphology";
import forceAtlas2 from "graphology-layout-forceatlas2";
import { Sigma } from "sigma";

import type { GraphNode, GraphEdge } from "@/types/graph";

// Re-export for consumers that imported directly from this file
export type { GraphNode, GraphEdge };

interface GraphViewProps {
  nodes: GraphNode[];
  edges: GraphEdge[];
  className?: string;
  highlightedNodeIds?: Set<string>;
  selectedNodeId?: string | null;
  onNodeClick?: (nodeId: string) => void;
  /** Called once after the Sigma instance is created (useful for zoom listeners). */
  onSigmaReady?: (sigma: Sigma) => void;
}

/** Default colour palette by STIX type */
function nodeColor(stixType?: string, defaultColor?: string): string {
  const palette: Record<string, string> = {
    "threat-actor": "#ef4444",
    malware: "#f97316",
    "attack-pattern": "#eab308",
    campaign: "#a855f7",
    identity: "#3b82f6",
    tool: "#06b6d4",
    location: "#10b981",
    vulnerability: "#f43f5e",
  };
  if (stixType && palette[stixType]) return palette[stixType];
  return defaultColor ?? "#6366f1";
}

export default function GraphView({
  nodes,
  edges,
  className,
  highlightedNodeIds,
  selectedNodeId,
  onNodeClick,
  onSigmaReady,
}: GraphViewProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const sigmaRef = useRef<Sigma | null>(null);
  const graphRef = useRef<Graph | null>(null);

  // ── Initial render ──────────────────────────────────────────────────────────
  useEffect(() => {
    if (!containerRef.current) return;

    const graph = new Graph();
    graphRef.current = graph;

    nodes.forEach(({ id, label, x, y, size = 5, color, stixType }) => {
      graph.addNode(id, {
        label,
        x,
        y,
        size,
        color: nodeColor(stixType, color),
        // store originals for highlight restore
        originalColor: nodeColor(stixType, color),
        stixType,
      });
    });

    edges.forEach(({ id, source, target, label }) => {
      if (graph.hasNode(source) && graph.hasNode(target)) {
        graph.addEdgeWithKey(id, source, target, { label });
      }
    });

    // Force-directed layout (sync, 50 iterations)
    if (graph.order > 0) {
      try {
        forceAtlas2.assign(graph, { iterations: 50 });
      } catch {
        // FA2 may throw if positions are degenerate; positions remain as-is
      }
    }

    sigmaRef.current = new Sigma(graph, containerRef.current, {
      renderEdgeLabels: false,
      defaultEdgeColor: "#e5e7eb",
      defaultNodeColor: "#6366f1",
    });

    // Notify parent so it can attach zoom/camera listeners
    onSigmaReady?.(sigmaRef.current);

    // Node click → call onNodeClick prop
    sigmaRef.current.on("clickNode", ({ node }: { node: string }) => {
      onNodeClick?.(node);
    });

    return () => {
      sigmaRef.current?.kill();
      sigmaRef.current = null;
      graphRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodes, edges]);

  // ── Highlight updates ───────────────────────────────────────────────────────
  useEffect(() => {
    const graph = graphRef.current;
    if (!graph) return;

    graph.forEachNode((nodeId: string) => {
      const original: string =
        graph.getNodeAttribute(nodeId, "originalColor") ?? "#6366f1";
      const isHighlighted = highlightedNodeIds?.has(nodeId) ?? false;
      const isSelected = selectedNodeId === nodeId;

      let color = original;
      if (isSelected)
        color = "#f59e0b"; // amber for selected
      else if (isHighlighted) color = "#ef4444"; // red for alerted

      graph.setNodeAttribute(nodeId, "color", color);
    });

    sigmaRef.current?.refresh();
  }, [highlightedNodeIds, selectedNodeId]);

  return (
    <div
      ref={containerRef}
      className={className ?? "w-full h-full"}
      aria-label="Knowledge graph visualisation"
      role="presentation"
    />
  );
}
