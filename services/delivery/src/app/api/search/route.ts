import { NextRequest, NextResponse } from "next/server";

/**
 * POST /api/search — triggers on-demand ingestion via the Aggregator.
 *
 * The Aggregator fans out to MCP plugins, queues Kafka events, and returns
 * 202 Accepted with { search_id, events_queued, queued_by_source }.
 * The processor then runs the pipeline stages; progress is emitted as
 * "pipeline_stage" Socket.io events by the gateway.
 *
 * To query already-ingested entities use POST /api/query (Processor).
 */

const AGGREGATOR_URL = process.env.AGGREGATOR_URL ?? "http://localhost:8080";

export async function POST(request: NextRequest) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }

  const { query, sources } =
    (body as { query?: unknown; sources?: unknown }) ?? {};

  if (!query || typeof query !== "string") {
    return NextResponse.json({ error: "query is required" }, { status: 400 });
  }

  let response: Response;
  try {
    response = await fetch(`${AGGREGATOR_URL}/search`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, sources }),
    });
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Aggregator unreachable";
    return NextResponse.json({ error: msg }, { status: 502 });
  }

  if (!response.ok) {
    const errBody = await response.json().catch(() => ({}));
    return NextResponse.json(errBody, { status: response.status });
  }

  const data: unknown = await response.json();
  return NextResponse.json(data, { status: response.status });
}
