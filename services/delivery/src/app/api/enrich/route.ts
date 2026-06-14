import { NextRequest, NextResponse } from "next/server";

/**
 * POST /api/enrich — request targeted enrichment for a specific entity.
 *
 * The UI calls this when a user clicks "Enrich" on a knowledge graph node.
 * The request is forwarded to the Aggregator POST /enrich endpoint which fans
 * out to configured MCP plugins and publishes fresh raw events back into the
 * Kafka pipeline.  Results flow through the Processor (grounding gate included)
 * and appear as real-time updates via the WebSocket alert stream.
 *
 * This is the "manual approval" gate for recursive enrichment: users decide
 * which entities to expand rather than the system recursing automatically.
 */

const AGGREGATOR_URL = process.env.AGGREGATOR_URL ?? "http://localhost:8000";

interface EnrichEntityMeta {
  name: string;
  type?: string;
  description?: string;
}

interface EnrichRequest {
  entity: EnrichEntityMeta;
  plugins?: string[];
  max_results?: number;
  tenant_id?: string;
}

export async function POST(request: NextRequest) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }

  const {
    entity,
    plugins,
    max_results,
    tenant_id = "default",
  } = (body as EnrichRequest) ?? {};

  if (!entity?.name?.trim()) {
    return NextResponse.json(
      { error: "entity.name is required" },
      { status: 400 },
    );
  }

  let response: Response;
  try {
    response = await fetch(`${AGGREGATOR_URL}/enrich`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ entity, plugins, max_results, tenant_id }),
    });
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Aggregator unreachable";
    return NextResponse.json({ error: msg }, { status: 502 });
  }

  if (!response.ok) {
    return NextResponse.json(
      { error: "Enrichment request failed" },
      { status: response.status },
    );
  }

  const data = await response.json();
  return NextResponse.json(data, { status: 202 });
}
