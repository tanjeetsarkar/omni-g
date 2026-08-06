import { NextRequest, NextResponse } from "next/server";

/**
 * POST /api/query/expand — Dynamic context expansion route.
 *
 * Proxies to the Processor `/query/expand` endpoint to fetch multi-hop
 * neighborhood entities and relationships for active ECharts drilldown.
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
    anchor_node_id,
    current_depth = 1,
    target_depth = 2,
    tenant_id = "default",
  } = (body as {
    anchor_node_id?: unknown;
    current_depth?: unknown;
    target_depth?: unknown;
    tenant_id?: unknown;
  }) ?? {};

  if (!anchor_node_id || typeof anchor_node_id !== "string") {
    return NextResponse.json(
      { error: "anchor_node_id is required" },
      { status: 400 },
    );
  }

  let response: Response;
  try {
    response = await fetch(`${PROCESSOR_URL}/query/expand`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        anchor_node_id,
        current_depth,
        target_depth,
        tenant_id,
      }),
    });
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Processor unreachable";
    return NextResponse.json({ error: msg }, { status: 502 });
  }

  if (!response.ok) {
    return NextResponse.json(
      { error: "Expansion query failed" },
      { status: response.status },
    );
  }

  const data = await response.json();
  return NextResponse.json(data);
}
