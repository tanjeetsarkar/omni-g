import {
  transformToRadialTreeData,
  EvidenceNode,
  EvidenceEdge,
  getTypeColor,
} from "../useEChartsGraphAdapter";

describe("useEChartsGraphAdapter transformToRadialTreeData", () => {
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

  it("transforms multi-hop nodes and edges into radial tree format", () => {
    const { treeData, nodes, links } = transformToRadialTreeData(
      mockNodes,
      mockEdges,
    );

    expect(treeData).not.toBeNull();
    expect(nodes.length).toBeGreaterThanOrEqual(3);
    expect(links.length).toBeGreaterThanOrEqual(2);

    // Root is dr_smith (degree 2 = most connected)
    const root = treeData as Record<string, unknown>;
    expect(root.name).toBe("dr_smith");

    // Root should have children
    const children = root.children as Record<string, unknown>[];
    expect(children).toBeDefined();
    expect(children.length).toBeGreaterThanOrEqual(1);
  });

  it("picks the highest-degree node as tree root", () => {
    const { treeData } = transformToRadialTreeData(mockNodes, mockEdges);
    const root = treeData as Record<string, unknown>;
    // hospital_123 has degree 1, dr_smith has degree 2. dr_smith should be root.
    // But wait: hospital_123 ↔ dr_smith, dr_smith ↔ trial_2025
    // hospital_123 degree = 1, dr_smith degree = 2, trial_2025 degree = 1
    // dr_smith has the highest degree (2), so it should be root.
    expect(root.name).toBe("dr_smith");
  });

  it("rich-text label includes type badge, title, and source tag", () => {
    const nodesWithProvenance: EvidenceNode[] = [
      {
        id: "hospital_123",
        label: "Johns Hopkins Hospital",
        type: "FACILITY",
        score: 0.95,
        depth: 0,
        source_name: "PubMed Central",
        sub_entity_count: 12,
      },
    ];
    const { nodes } = transformToRadialTreeData(nodesWithProvenance, []);
    const label = nodes[0].label as string;

    expect(label).toContain("{typeBadge| FACILITY }");
    expect(label).toContain("{title| Johns Hopkins Hospital }");
    expect(label).toContain("+12 links");
    expect(label).toContain("📍 PubMed Central");
  });

  it("emits x/y coordinates for radial layout", () => {
    const { nodes } = transformToRadialTreeData(mockNodes, mockEdges);

    for (const node of nodes) {
      expect(typeof node.x).toBe("number");
      expect(typeof node.y).toBe("number");
      expect(Number.isFinite(node.x!)).toBe(true);
      expect(Number.isFinite(node.y!)).toBe(true);
    }
  });

  it("places nodes at different radial distances based on depth", () => {
    const { nodes } = transformToRadialTreeData(mockNodes, mockEdges);

    // Nodes at different depths should be at different distances from origin
    const distances = nodes.map((n) => {
      const nx = (n.x as number) ?? 0;
      const ny = (n.y as number) ?? 0;
      return Math.sqrt(nx * nx + ny * ny);
    });

    // Not all nodes should be at the same distance
    const uniqueDistances = new Set(distances.map((d) => d.toFixed(0)));
    expect(uniqueDistances.size).toBeGreaterThan(1);
  });

  it("returns empty result for empty nodes", () => {
    const { treeData, nodes, links } = transformToRadialTreeData([], []);
    expect(treeData).toBeNull();
    expect(nodes).toHaveLength(0);
    expect(links).toHaveLength(0);
  });

  it("handles single node with no edges", () => {
    const { treeData, nodes, links } = transformToRadialTreeData(
      [mockNodes[0]],
      [],
    );

    expect(treeData).not.toBeNull();
    expect(nodes).toHaveLength(1);
    expect(links).toHaveLength(0);

    const root = treeData as Record<string, unknown>;
    expect(root.name).toBe("hospital_123");
  });
});
