"use client";

/**
 * useGraphFilter — filter/search state for the Knowledge Graph dashboard.
 *
 * Provides:
 *   - filteredNodes / filteredEdges based on current filter state
 *   - availableTypes: all unique stixType values (sorted)
 *   - toggle / confidence / search / reset controls
 *
 * When new nodes arrive (polling update), any previously unseen stixType is
 * automatically added to enabledTypes.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import type { GraphEdge, GraphNode } from "@/types/graph";

export interface FilterState {
  enabledTypes: Set<string>;
  minConfidence: number;
  searchQuery: string;
}

export function useGraphFilter(
  nodes: GraphNode[],
  edges: GraphEdge[],
): {
  filteredNodes: GraphNode[];
  filteredEdges: GraphEdge[];
  filterState: FilterState;
  availableTypes: string[];
  toggleType: (type: string) => void;
  setMinConfidence: (v: number) => void;
  setSearchQuery: (q: string) => void;
  resetFilters: () => void;
} {
  // All unique stixType values present in the current node set, sorted A→Z
  const availableTypes = useMemo(() => {
    const types = new Set<string>();
    nodes.forEach((n) => {
      if (n.stixType) types.add(n.stixType);
    });
    return Array.from(types).sort();
  }, [nodes]);

  // Track which types have been seen so we only auto-enable *new* ones,
  // not types the user explicitly unchecked.
  const seenTypesRef = useRef<Set<string>>(new Set<string>());

  const [filterState, setFilterState] = useState<FilterState>({
    enabledTypes: new Set<string>(),
    minConfidence: 0,
    searchQuery: "",
  });

  // When availableTypes changes, enable any types not previously seen
  useEffect(() => {
    const genuinelyNew = availableTypes.filter(
      (t) => !seenTypesRef.current.has(t),
    );
    if (genuinelyNew.length === 0) return;

    genuinelyNew.forEach((t) => seenTypesRef.current.add(t));
    setFilterState((prev) => {
      const next = new Set(prev.enabledTypes);
      genuinelyNew.forEach((t) => next.add(t));
      return { ...prev, enabledTypes: next };
    });
  }, [availableTypes]);

  // ── Derived filtered data ──────────────────────────────────────────────────

  const filteredNodes = useMemo(() => {
    const query = filterState.searchQuery.toLowerCase();
    return nodes.filter((node) => {
      // Type filter: if enabledTypes is non-empty, the node's stixType must be in it.
      // Nodes without a stixType always pass.
      if (
        filterState.enabledTypes.size > 0 &&
        node.stixType &&
        !filterState.enabledTypes.has(node.stixType)
      ) {
        return false;
      }
      // Confidence filter: nodes without confidence always pass
      if (
        node.confidence !== undefined &&
        node.confidence < filterState.minConfidence
      ) {
        return false;
      }
      // Search filter
      if (query && !node.label.toLowerCase().includes(query)) {
        return false;
      }
      return true;
    });
  }, [nodes, filterState]);

  const filteredNodeIds = useMemo(
    () => new Set(filteredNodes.map((n) => n.id)),
    [filteredNodes],
  );

  const filteredEdges = useMemo(
    () =>
      edges.filter(
        (e) => filteredNodeIds.has(e.source) && filteredNodeIds.has(e.target),
      ),
    [edges, filteredNodeIds],
  );

  // ── Controls ───────────────────────────────────────────────────────────────

  const toggleType = (type: string) => {
    setFilterState((prev) => {
      const next = new Set(prev.enabledTypes);
      if (next.has(type)) {
        next.delete(type);
      } else {
        next.add(type);
      }
      return { ...prev, enabledTypes: next };
    });
  };

  const setMinConfidence = (v: number) => {
    setFilterState((prev) => ({ ...prev, minConfidence: v }));
  };

  const setSearchQuery = (q: string) => {
    setFilterState((prev) => ({ ...prev, searchQuery: q }));
  };

  const resetFilters = () => {
    setFilterState({
      enabledTypes: new Set(availableTypes),
      minConfidence: 0,
      searchQuery: "",
    });
    // Re-sync seenTypes to current availableTypes on reset
    seenTypesRef.current = new Set(availableTypes);
  };

  return {
    filteredNodes,
    filteredEdges,
    filterState,
    availableTypes,
    toggleType,
    setMinConfidence,
    setSearchQuery,
    resetFilters,
  };
}
