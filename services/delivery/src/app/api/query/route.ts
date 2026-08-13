import { NextRequest, NextResponse } from "next/server";
import type { SearchResponse } from "../../../types/entities";

/**
 * POST /api/query — retrieve already-ingested entities from the Processor.
 *
 * Embeds the query, searches Qdrant, fetches matched entities + Neo4j
 * neighbours, and returns them.  Used by the dashboard "Refresh Workspace"
 * CTA after the ingestion pipeline has completed.
 */

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
    limit = 50,
    relevance_threshold = 0.0,
    traversal_depth,
    search_id,
  } = (body as {
    query?: unknown;
    tenant_id?: unknown;
    limit?: unknown;
    relevance_threshold?: unknown;
    traversal_depth?: unknown;
    search_id?: unknown;
  }) ?? {};

  if (!query || typeof query !== "string") {
    return NextResponse.json({ error: "query is required" }, { status: 400 });
  }

  // V4 Track 2: forward τ / D_max to the Processor /search endpoint.
  const payload: Record<string, unknown> = { query, tenant_id, limit };
  if (typeof relevance_threshold === "number" && relevance_threshold > 0) {
    payload.relevance_threshold = relevance_threshold;
  }
  if (typeof traversal_depth === "number") {
    payload.traversal_depth = traversal_depth;
  }
  if (typeof search_id === "string") {
    payload.search_id = search_id;
  }

  let response: Response;
  try {
    response = await fetch(`${PROCESSOR_URL}/search`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Processor unreachable";
    return NextResponse.json({ error: msg }, { status: 502 });
  }

  if (!response.ok) {
    return NextResponse.json(
      { error: "Query failed" },
      { status: response.status },
    );
  }

  const data: SearchResponse = await response.json();
  return NextResponse.json(data);
}
