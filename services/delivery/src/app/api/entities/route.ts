import { NextRequest, NextResponse } from "next/server";
import type { SearchResponse } from "../../../types/entities";

/**
 * POST /api/entities — fetch entities from Neo4j directly by canonical ID.
 *
 * Used by useRealtimeNodes to hydrate real-time WebSocket alerts without
 * triggering a new ingestion cycle.  Proxies to the Processor /entities
 * endpoint which returns matched entities plus 1-hop neighbours.
 */

const PROCESSOR_URL = process.env.PROCESSOR_URL ?? "http://localhost:8001";

export async function POST(request: NextRequest) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }

  const { entity_ids, tenant_id = "default" } =
    (body as { entity_ids?: unknown; tenant_id?: unknown }) ?? {};

  if (!Array.isArray(entity_ids) || entity_ids.length === 0) {
    return NextResponse.json(
      { error: "entity_ids must be a non-empty array" },
      { status: 400 },
    );
  }

  let response: Response;
  try {
    response = await fetch(`${PROCESSOR_URL}/entities`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ entity_ids, tenant_id }),
    });
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Processor unreachable";
    return NextResponse.json({ error: msg }, { status: 502 });
  }

  if (!response.ok) {
    return NextResponse.json(
      { error: "Entity fetch failed" },
      { status: response.status },
    );
  }

  const data: SearchResponse = await response.json();
  return NextResponse.json(data);
}
