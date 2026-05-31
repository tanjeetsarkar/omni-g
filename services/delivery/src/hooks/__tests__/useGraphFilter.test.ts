/**
 * useGraphFilter hook tests
 */

import { renderHook, act } from "@testing-library/react";
import { useGraphFilter } from "../useGraphFilter";
import type { GraphNode, GraphEdge } from "@/types/graph";

const nodes: GraphNode[] = [
  {
    id: "n1",
    label: "Emotet",
    x: 0,
    y: 0,
    stixType: "malware",
    confidence: 0.9,
  },
  {
    id: "n2",
    label: "APT28",
    x: 1,
    y: 1,
    stixType: "threat-actor",
    confidence: 0.8,
  },
  {
    id: "n3",
    label: "Spear Phishing",
    x: 2,
    y: 2,
    stixType: "attack-pattern",
    confidence: 0.6,
  },
  {
    id: "n4",
    label: "EternalBlue",
    x: 3,
    y: 3,
    stixType: "vulnerability",
    confidence: 0.4,
  },
];

const edges: GraphEdge[] = [
  { id: "e1", source: "n1", target: "n2", label: "uses" },
  { id: "e2", source: "n2", target: "n3", label: "uses" },
  { id: "e3", source: "n3", target: "n4", label: "targets" },
];

describe("useGraphFilter", () => {
  it("returns all nodes when no filters have been changed", () => {
    const { result } = renderHook(() => useGraphFilter(nodes, edges));
    expect(result.current.filteredNodes).toHaveLength(nodes.length);
  });

  it("returns all edges when no filters have been changed", () => {
    const { result } = renderHook(() => useGraphFilter(nodes, edges));
    expect(result.current.filteredEdges).toHaveLength(edges.length);
  });

  it("hides a node when its stixType is toggled off", () => {
    const { result } = renderHook(() => useGraphFilter(nodes, edges));
    act(() => {
      result.current.toggleType("malware");
    });
    expect(
      result.current.filteredNodes.find((n) => n.id === "n1"),
    ).toBeUndefined();
    // other nodes still visible
    expect(
      result.current.filteredNodes.find((n) => n.id === "n2"),
    ).toBeDefined();
  });

  it("excludes edges where source node is filtered out", () => {
    const { result } = renderHook(() => useGraphFilter(nodes, edges));
    act(() => {
      result.current.toggleType("malware"); // removes n1
    });
    expect(
      result.current.filteredEdges.find((e) => e.id === "e1"),
    ).toBeUndefined();
  });

  it("excludes edges where target node is filtered out", () => {
    const { result } = renderHook(() => useGraphFilter(nodes, edges));
    act(() => {
      result.current.toggleType("threat-actor"); // removes n2
    });
    // e1 (n1→n2) should be gone because n2 is filtered
    expect(
      result.current.filteredEdges.find((e) => e.id === "e1"),
    ).toBeUndefined();
  });

  it("filters nodes below minConfidence", () => {
    const { result } = renderHook(() => useGraphFilter(nodes, edges));
    act(() => {
      result.current.setMinConfidence(0.5);
    });
    // n4 (confidence 0.4) should be hidden
    expect(
      result.current.filteredNodes.find((n) => n.id === "n4"),
    ).toBeUndefined();
    // n3 (confidence 0.6) should still be visible
    expect(
      result.current.filteredNodes.find((n) => n.id === "n3"),
    ).toBeDefined();
  });

  it("filters nodes by searchQuery (case-insensitive)", () => {
    const { result } = renderHook(() => useGraphFilter(nodes, edges));
    act(() => {
      result.current.setSearchQuery("APT");
    });
    expect(result.current.filteredNodes).toHaveLength(1);
    expect(result.current.filteredNodes[0].id).toBe("n2");
  });

  it("returns availableTypes as a sorted list of unique stixTypes", () => {
    const { result } = renderHook(() => useGraphFilter(nodes, edges));
    expect(result.current.availableTypes).toEqual([
      "attack-pattern",
      "malware",
      "threat-actor",
      "vulnerability",
    ]);
  });

  it("resetFilters restores all nodes and clears search/confidence", () => {
    const { result } = renderHook(() => useGraphFilter(nodes, edges));
    act(() => {
      result.current.toggleType("malware");
      result.current.setMinConfidence(0.7);
      result.current.setSearchQuery("APT");
    });
    act(() => {
      result.current.resetFilters();
    });
    expect(result.current.filteredNodes).toHaveLength(nodes.length);
    expect(result.current.filterState.minConfidence).toBe(0);
    expect(result.current.filterState.searchQuery).toBe("");
  });

  it("automatically enables a newly seen stixType when nodes update", () => {
    const initial = [nodes[0], nodes[1]]; // malware + threat-actor
    const { result, rerender } = renderHook(
      ({ n }: { n: GraphNode[] }) => useGraphFilter(n, []),
      { initialProps: { n: initial } },
    );

    const updated = [
      ...initial,
      {
        id: "n5",
        label: "CVE-9999",
        x: 0,
        y: 0,
        stixType: "vulnerability",
        confidence: 0.8,
      },
    ];
    rerender({ n: updated });

    expect(result.current.filterState.enabledTypes.has("vulnerability")).toBe(
      true,
    );
  });

  it("does not re-enable a type the user explicitly unchecked on data refresh", () => {
    const { result, rerender } = renderHook(
      ({ n }: { n: GraphNode[] }) => useGraphFilter(n, []),
      { initialProps: { n: nodes } },
    );

    // User unchecks malware
    act(() => {
      result.current.toggleType("malware");
    });
    expect(result.current.filterState.enabledTypes.has("malware")).toBe(false);

    // Simulate a data refresh with the same nodes
    rerender({ n: [...nodes] });

    // malware should still be unchecked
    expect(result.current.filterState.enabledTypes.has("malware")).toBe(false);
  });
});
