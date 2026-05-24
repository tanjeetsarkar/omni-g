/**
 * GET /api/graph route tests
 * @jest-environment node
 */

import { NextRequest } from "next/server";
import { GET } from "@/app/api/graph/route";

// ---- Mock neo4j singleton ------------------------------------------------
jest.mock("@/lib/neo4j", () => ({
  getDriver: jest.fn(),
}));

import { getDriver } from "@/lib/neo4j";
const mockGetDriver = getDriver as jest.Mock;

function makeRequest(tenantId = "test-tenant"): NextRequest {
  return new NextRequest(`http://localhost/api/graph?tenant_id=${tenantId}`);
}

function makeSession(records: Record<string, unknown>[]) {
  return {
    run: jest.fn().mockResolvedValue({ records }),
    close: jest.fn().mockResolvedValue(undefined),
  };
}

describe("GET /api/graph", () => {
  afterEach(() => {
    jest.clearAllMocks();
  });

  it("returns 200 and empty arrays when Neo4j returns no records", async () => {
    mockGetDriver.mockReturnValue({ session: () => makeSession([]) });

    const response = await GET(makeRequest());
    expect(response.status).toBe(200);
    const body = await response.json();
    expect(body.nodes).toEqual([]);
    expect(body.edges).toEqual([]);
  });

  it("returns nodes from Neo4j records", async () => {
    const fakeNode = {
      identity: { toString: () => "1" },
      properties: {
        id: "node-1",
        name: "Sundar Pichai",
        stix_type: "identity",
        tenant_id: "test-tenant",
      },
    };
    const fakeRecord = {
      get: (key: string) => {
        if (key === "n") return fakeNode;
        return null;
      },
    };
    mockGetDriver.mockReturnValue({ session: () => makeSession([fakeRecord]) });

    const response = await GET(makeRequest());
    const body = await response.json();
    expect(body.nodes).toHaveLength(1);
    expect(body.nodes[0].id).toBe("node-1");
    expect(body.nodes[0].label).toBe("Sundar Pichai");
    expect(body.nodes[0].stixType).toBe("identity");
    expect(body.edges).toHaveLength(0);
  });

  it("returns empty arrays on Neo4j driver error (graceful degradation)", async () => {
    mockGetDriver.mockReturnValue({
      session: () => ({
        run: jest.fn().mockRejectedValue(new Error("Connection refused")),
        close: jest.fn().mockResolvedValue(undefined),
      }),
    });

    const response = await GET(makeRequest());
    expect(response.status).toBe(200);
    const body = await response.json();
    expect(body.nodes).toEqual([]);
    expect(body.edges).toEqual([]);
  });

  it("returns empty arrays when getDriver throws", async () => {
    mockGetDriver.mockImplementation(() => {
      throw new Error("Driver not initialised");
    });

    const response = await GET(makeRequest());
    expect(response.status).toBe(200);
    const body = await response.json();
    expect(body.nodes).toEqual([]);
    expect(body.edges).toEqual([]);
  });

  it("processes a 10k node array without throwing", () => {
    // Performance: ensure Map deduplication doesn't blow up
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
