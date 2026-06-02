/**
 * @jest-environment node
 *
 * Unit tests for POST /api/search route.
 * Must run in Node environment — NextRequest requires Web API Request.
 */
import { NextRequest } from "next/server";
import { POST } from "@/app/api/search/route";

describe("POST /api/search", () => {
  it("returns 400 when query is missing", async () => {
    const req = new NextRequest("http://localhost/api/search", {
      method: "POST",
      body: JSON.stringify({ tenant_id: "default" }),
      headers: { "Content-Type": "application/json" },
    });

    const res = await POST(req);
    expect(res.status).toBe(400);
    const body = await res.json();
    expect(body.error).toBe("query is required");
  });

  it("returns 400 when body is empty JSON", async () => {
    const req = new NextRequest("http://localhost/api/search", {
      method: "POST",
      body: JSON.stringify({}),
      headers: { "Content-Type": "application/json" },
    });

    const res = await POST(req);
    expect(res.status).toBe(400);
  });

  it("returns 400 when query is not a string", async () => {
    const req = new NextRequest("http://localhost/api/search", {
      method: "POST",
      body: JSON.stringify({ query: 42 }),
      headers: { "Content-Type": "application/json" },
    });

    const res = await POST(req);
    expect(res.status).toBe(400);
  });

  it("returns 400 on invalid JSON body", async () => {
    const req = new NextRequest("http://localhost/api/search", {
      method: "POST",
      body: "not-json",
      headers: { "Content-Type": "application/json" },
    });

    const res = await POST(req);
    expect(res.status).toBe(400);
  });

  it("proxies to processor and returns data on success", async () => {
    const mockData = {
      entities: [{ id: "entity--1", name: "Test" }],
      relationships: [],
    };
    global.fetch = jest.fn().mockResolvedValueOnce({
      ok: true,
      json: async () => mockData,
    } as Response);

    const req = new NextRequest("http://localhost/api/search", {
      method: "POST",
      body: JSON.stringify({
        query: "test entity",
        tenant_id: "default",
        limit: 10,
      }),
      headers: { "Content-Type": "application/json" },
    });

    const res = await POST(req);
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body).toEqual(mockData);
  });

  it("returns 502 when processor is unreachable", async () => {
    global.fetch = jest.fn().mockRejectedValueOnce(new Error("ECONNREFUSED"));

    const req = new NextRequest("http://localhost/api/search", {
      method: "POST",
      body: JSON.stringify({ query: "test" }),
      headers: { "Content-Type": "application/json" },
    });

    const res = await POST(req);
    expect(res.status).toBe(502);
  });
});
