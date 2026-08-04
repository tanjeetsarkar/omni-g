/**
 * GET /api/assessments route tests
 * @jest-environment node
 */

import { GET } from "@/app/api/assessments/route";
import { NextRequest } from "next/server";

global.fetch = jest.fn();

function makeRequest(url: string): NextRequest {
  return new NextRequest(url);
}

describe("GET /api/assessments", () => {
  beforeEach(() => {
    jest.resetAllMocks();
  });

  it("returns 400 when tenant_id is missing", async () => {
    const res = await GET(makeRequest("http://localhost:3000/api/assessments"));
    expect(res.status).toBe(400);
    const body = await res.json();
    expect(body.error).toBe("tenant_id is required");
  });

  it("forwards tenant_id to upstream Processor", async () => {
    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: async () => ({ assessments: [] }),
    });

    await GET(
      makeRequest("http://localhost:3000/api/assessments?tenant_id=acme"),
    );

    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining("tenant_id=acme"),
      expect.anything(),
    );
  });

  it("forwards optional kiq_id to upstream Processor", async () => {
    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: async () => ({ assessments: [] }),
    });

    await GET(
      makeRequest(
        "http://localhost:3000/api/assessments?tenant_id=acme&kiq_id=kiq--abc",
      ),
    );

    const calledUrl = (global.fetch as jest.Mock).mock.calls[0][0] as string;
    expect(calledUrl).toContain("kiq_id=kiq--abc");
  });

  it("returns assessments from upstream", async () => {
    const mockAssessments = [
      {
        id: "assessment--a1",
        tenant_id: "acme",
        kiq_id: "kiq--xyz",
        conclusion: "Test conclusion",
        confidence: { low: 0.3, mid: 0.6, high: 0.8 },
        reasoning: "Test reasoning",
        assumptions: [],
        supporting_evidence_ids: [],
        contradicting_evidence_ids: [],
        collection_gaps: [],
        recommended_next_actions: [],
        status: "PUBLISHED",
        produced_by: "PROCESSOR",
        version: 1,
        hypothesis_id: null,
        superseded_by_id: null,
        created: "2026-07-05T10:00:00Z",
        modified: "2026-07-05T10:00:00Z",
      },
    ];
    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: async () => ({ assessments: mockAssessments }),
    });

    const res = await GET(
      makeRequest("http://localhost:3000/api/assessments?tenant_id=acme"),
    );
    const body = await res.json();

    expect(body.assessments).toEqual(mockAssessments);
  });

  it("returns empty assessments when Processor is unreachable", async () => {
    (global.fetch as jest.Mock).mockRejectedValueOnce(
      new Error("ECONNREFUSED"),
    );

    const res = await GET(
      makeRequest("http://localhost:3000/api/assessments?tenant_id=acme"),
    );
    const body = await res.json();

    expect(res.status).toBe(200);
    expect(body.assessments).toEqual([]);
  });

  it("returns empty assessments when Processor returns non-ok status", async () => {
    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: false,
      status: 404,
    });

    const res = await GET(
      makeRequest("http://localhost:3000/api/assessments?tenant_id=acme"),
    );
    const body = await res.json();

    expect(res.status).toBe(200);
    expect(body.assessments).toEqual([]);
  });
});
