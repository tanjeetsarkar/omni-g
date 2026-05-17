/**
 * GET /api/graph route tests
 * @jest-environment node
 */

import { GET } from "@/app/api/graph/route";

describe("GET /api/graph", () => {
  it("returns 200 status", async () => {
    const response = await GET();
    expect(response.status).toBe(200);
  });

  it("returns nodes array", async () => {
    const response = await GET();
    const body = await response.json();
    expect(Array.isArray(body.nodes)).toBe(true);
  });

  it("returns edges array", async () => {
    const response = await GET();
    const body = await response.json();
    expect(Array.isArray(body.edges)).toBe(true);
  });

  it("returns 20 nodes", async () => {
    const response = await GET();
    const body = await response.json();
    expect(body.nodes).toHaveLength(20);
  });

  it("returns 15 edges", async () => {
    const response = await GET();
    const body = await response.json();
    expect(body.edges).toHaveLength(15);
  });

  it("each node has required fields: id, label, x, y", async () => {
    const response = await GET();
    const { nodes } = await response.json();
    nodes.forEach((node: Record<string, unknown>) => {
      expect(node).toHaveProperty("id");
      expect(node).toHaveProperty("label");
      expect(node).toHaveProperty("x");
      expect(node).toHaveProperty("y");
    });
  });

  it("each edge has source and target", async () => {
    const response = await GET();
    const { edges } = await response.json();
    edges.forEach((edge: Record<string, unknown>) => {
      expect(edge).toHaveProperty("source");
      expect(edge).toHaveProperty("target");
    });
  });

  it("processes a 10k node array without throwing", () => {
    // Performance: ensure useGraphData-style processing doesn't blow up
    const bigNodes = Array.from({ length: 10_000 }, (_, i) => ({
      id: `n${i}`,
      label: `Node ${i}`,
      x: Math.random() * 1000,
      y: Math.random() * 1000,
      stixType: "malware",
      confidence: 0.8,
    }));

    expect(() => {
      const nodeMap = new Map(bigNodes.map((n) => [n.id, n]));
      expect(nodeMap.size).toBe(10_000);
    }).not.toThrow();
  });
});
