/**
 * GET /api/briefings route tests
 * @jest-environment node
 */

import { GET } from "@/app/api/briefings/route";
import { NextRequest } from "next/server";

global.fetch = jest.fn();

function makeRequest(url: string): NextRequest {
  return new NextRequest(url);
}

describe("GET /api/briefings", () => {
  beforeEach(() => {
    jest.resetAllMocks();
  });

  it("forwards tenant_id query param to upstream processor", async () => {
    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: async () => ({ briefings: [] }),
    });

    await GET(
      makeRequest("http://localhost:3000/api/briefings?tenant_id=acme"),
    );

    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining("tenant_id=acme"),
      expect.anything(),
    );
  });

  it("returns briefings from upstream", async () => {
    const mockBriefings = [
      { id: "b1", date: "2025-01-01", title: "Morning Brief" },
    ];
    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: async () => ({ briefings: mockBriefings }),
    });

    const res = await GET(
      makeRequest("http://localhost:3000/api/briefings?tenant_id=acme"),
    );
    const body = await res.json();

    expect(body.briefings).toEqual(mockBriefings);
  });

  it("returns fallback when fetch throws", async () => {
    (global.fetch as jest.Mock).mockRejectedValueOnce(
      new Error("Network error"),
    );

    const res = await GET(
      makeRequest("http://localhost:3000/api/briefings?tenant_id=acme"),
    );
    const body = await res.json();

    expect(body.briefings).toEqual([]);
    expect(body.error).toBe("processor unavailable");
  });

  it("returns fallback when upstream returns non-ok status", async () => {
    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: false,
      status: 503,
    });

    const res = await GET(
      makeRequest("http://localhost:3000/api/briefings?tenant_id=acme"),
    );
    const body = await res.json();

    expect(body.briefings).toEqual([]);
    expect(body.error).toBe("processor unavailable");
  });

  it("returns 200 even on upstream failure", async () => {
    (global.fetch as jest.Mock).mockRejectedValueOnce(new Error("timeout"));

    const res = await GET(makeRequest("http://localhost:3000/api/briefings"));
    expect(res.status).toBe(200);
  });
});
