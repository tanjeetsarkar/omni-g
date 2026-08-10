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

    // Node 0 assertions — x/y added for static layout, confidence for tooltips
    expect(nodes[0].id).toBe("hospital_123");
    expect(nodes[0].name).toBe("hospital_123");
    expect(nodes[0].label).toBe("Johns Hopkins Hospital");
    expect(nodes[0].symbolSize).toBe(45);
    expect(nodes[0].category).toBe("FACILITY");
    expect(nodes[0].value).toBe(0.95);
    expect(nodes[0].rawContext).toBe("A famous hospital");
    expect(nodes[0].sourceId).toBe("src-1");
    expect(nodes[0].timestamp).toBe("2026-08-01T00:00:00Z");
    expect(typeof nodes[0].x).toBe("number");
    expect(typeof nodes[0].y).toBe("number");
    expect(nodes[0].confidence).toBe(0.95);

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

  it("emits x/y coordinates for static (layout: none) rendering", () => {
    const { nodes } = transformToEChartsData(mockNodes, mockEdges);

    for (const node of nodes) {
      expect(typeof node.x).toBe("number");
      expect(typeof node.y).toBe("number");
      expect(Number.isFinite(node.x)).toBe(true);
      expect(Number.isFinite(node.y)).toBe(true);
    }
  });

  it("places nodes in a circular distribution when >1 node", () => {
    const { nodes } = transformToEChartsData(mockNodes, mockEdges);

    // With 3 nodes, the angles should be 0, 2π/3, 4π/3 on a circle radius 300
    const radius = 300;

    // Each node should be at roughly radius distance from origin
    for (const node of nodes) {
      const dist = Math.sqrt(node.x * node.x + node.y * node.y);
      expect(dist).toBeCloseTo(radius, -1); // within ~10 due to floating point
    }

    // Nodes should be distinct positions (not all at the same spot)
    const positions = nodes.map((n) => `${n.x.toFixed(2)},${n.y.toFixed(2)}`);
    expect(new Set(positions).size).toBe(nodes.length);
  });
});
