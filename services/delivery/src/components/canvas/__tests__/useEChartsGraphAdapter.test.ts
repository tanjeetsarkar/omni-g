import {
  transformToEChartsData,
  EvidenceNode,
  EvidenceEdge,
  getTypeColor,
} from "../useEChartsGraphAdapter";

describe("useEChartsGraphAdapter transformToEChartsData", () => {
  const mockNodes: EvidenceNode[] = [
    {
      id: "hospital_123",
      label: "Johns Hopkins Hospital",
      type: "FACILITY",
      score: 0.95,
      depth: 0,
      raw_text: "A famous hospital",
      source_id: "src-1",
      created_at: "2026-08-01T00:00:00Z",
    },
    {
      id: "dr_smith",
      label: "Dr. Smith",
      type: "PERSON",
      score: 0.85,
      depth: 1,
      raw_text: "A famous doctor",
      source_id: "src-2",
      created_at: "2026-08-02T00:00:00Z",
    },
    {
      id: "trial_2025",
      label: "Immunotherapy Trial 2025",
      type: "STUDY",
      score: 0.75,
      depth: 2,
      raw_text: "A clinical trial",
      source_id: "src-3",
      created_at: "2026-08-03T00:00:00Z",
    },
  ];

  const mockEdges: EvidenceEdge[] = [
    {
      id: "rel-1",
      source_id: "hospital_123",
      target_id: "dr_smith",
      weight: 0.9,
    },
    {
      id: "rel-2",
      source_id: "dr_smith",
      target_id: "trial_2025",
      weight: 0.7,
    },
  ];

  it("transforms multi-hop nodes and edges into ECharts compliance format", () => {
    const { nodes, links } = transformToEChartsData(mockNodes, mockEdges);

    expect(nodes).toHaveLength(3);
    expect(links).toHaveLength(2);

    expect(nodes[0]).toEqual({
      id: "hospital_123",
      name: "hospital_123",
      label: "Johns Hopkins Hospital",
      symbolSize: 45,
      category: "FACILITY",
      value: 0.95,
      itemStyle: { color: getTypeColor("FACILITY") },
      rawContext: "A famous hospital",
      sourceId: "src-1",
      timestamp: "2026-08-01T00:00:00Z",
    });

    expect(links[0]).toEqual({
      source: "hospital_123",
      target: "dr_smith",
      value: 0.9,
      lineStyle: { width: 2.7, opacity: 0.6 },
    });
  });

  it("asserts root nodes (D=0) receive larger symbol size than leaf nodes (D=1, 2)", () => {
    const { nodes } = transformToEChartsData(mockNodes, mockEdges);

    const rootNode = nodes.find((n) => n.id === "hospital_123");
    const midNode = nodes.find((n) => n.id === "dr_smith");
    const leafNode = nodes.find((n) => n.id === "trial_2025");

    expect(rootNode?.symbolSize).toBe(45);
    expect(midNode?.symbolSize).toBe(32);
    expect(leafNode?.symbolSize).toBe(22);
  });
});
