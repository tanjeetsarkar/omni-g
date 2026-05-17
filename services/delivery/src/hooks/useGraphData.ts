"use client";

/**
 * useGraphData — polls GET /api/graph every 30 s.
 *
 * Returns { nodes, edges, loading, error }
 */

import { useCallback, useEffect, useState } from "react";
import type { GraphNode, GraphEdge } from "@/types/graph";

interface GraphDataResponse {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export function useGraphData(): {
  nodes: GraphNode[];
  edges: GraphEdge[];
  loading: boolean;
  error: string | null;
} {
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [edges, setEdges] = useState<GraphEdge[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      const res = await fetch("/api/graph");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: GraphDataResponse = await res.json();
      setNodes(data.nodes ?? []);
      setEdges(data.edges ?? []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load graph");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 30_000);
    return () => clearInterval(interval);
  }, [fetchData]);

  return { nodes, edges, loading, error };
}
