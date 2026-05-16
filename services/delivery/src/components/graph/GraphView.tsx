"use client";

/**
 * GraphView — Sigma.js WebGL graph renderer.
 *
 * Phase M5.2 will extend this with:
 *   - force-directed layout (ForceAtlas2)
 *   - semantic zooming (aggregate → individual)
 *   - Focus+Context filtering
 *   - real-time node/edge highlighting on incoming alerts
 *   - performance targets: 50k nodes rendered in <500ms
 *
 * This skeleton initialises a Sigma instance in a React ref and
 * tears it down on unmount.
 */
import { useEffect, useRef } from "react";

import Graph from "graphology";
import { Sigma } from "sigma";

export interface GraphNode {
  id: string;
  label: string;
  x: number;
  y: number;
  size?: number;
  color?: string;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  label?: string;
}

interface GraphViewProps {
  nodes: GraphNode[];
  edges: GraphEdge[];
  className?: string;
}

export default function GraphView({ nodes, edges, className }: GraphViewProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const sigmaRef = useRef<Sigma | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const graph = new Graph();

    nodes.forEach(({ id, label, x, y, size = 5, color = "#6366f1" }) => {
      graph.addNode(id, { label, x, y, size, color });
    });

    edges.forEach(({ id, source, target, label }) => {
      if (graph.hasNode(source) && graph.hasNode(target)) {
        graph.addEdgeWithKey(id, source, target, { label });
      }
    });

    sigmaRef.current = new Sigma(graph, containerRef.current, {
      renderEdgeLabels: false,
      defaultEdgeColor: "#e5e7eb",
      defaultNodeColor: "#6366f1",
    });

    return () => {
      sigmaRef.current?.kill();
      sigmaRef.current = null;
    };
  }, [nodes, edges]);

  return (
    <div
      ref={containerRef}
      className={className ?? "w-full h-full"}
      aria-label="Knowledge graph visualisation"
    />
  );
}
