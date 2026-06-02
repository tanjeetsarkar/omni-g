import { NextRequest, NextResponse } from "next/server";
import type { SearchResponse } from "../../../types/entities";

const PROCESSOR_URL = process.env.PROCESSOR_URL ?? "http://localhost:8001";

export async function POST(request: NextRequest) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }

  const {
    query,
    tenant_id = "default",
    limit = 20,
  } = (body as { query?: unknown; tenant_id?: unknown; limit?: unknown }) ?? {};

  if (!query || typeof query !== "string") {
    return NextResponse.json({ error: "query is required" }, { status: 400 });
  }

  let response: Response;
  try {
    response = await fetch(`${PROCESSOR_URL}/search`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, tenant_id, limit }),
    });
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Processor unreachable";
    return NextResponse.json({ error: msg }, { status: 502 });
  }

  if (!response.ok) {
    return NextResponse.json(
      { error: "Search failed" },
      { status: response.status },
    );
  }

  const data: SearchResponse = await response.json();
  return NextResponse.json(data);
}
