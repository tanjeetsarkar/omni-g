import { NextRequest, NextResponse } from "next/server";

/**
 * POST /api/synthesize — proxy to Processor's /synthesize endpoint.
 *
 * Takes context_units + query → LLMClient.generate() → BLUF summary.
 * Falls back to extractive summary if LLM unavailable.
 */

const PROCESSOR_URL = process.env.PROCESSOR_URL ?? "http://localhost:8001";

export async function POST(request: NextRequest) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }

  const { query, tenant_id, context_units } =
    (body as {
      query?: unknown;
      tenant_id?: unknown;
      context_units?: unknown;
    }) ?? {};

  if (!query || typeof query !== "string") {
    return NextResponse.json({ error: "query is required" }, { status: 400 });
  }

  let response: Response;
  try {
    response = await fetch(`${PROCESSOR_URL}/synthesize`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, tenant_id, context_units }),
    });
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Processor unreachable";
    return NextResponse.json({ error: msg }, { status: 502 });
  }

  if (!response.ok) {
    return NextResponse.json(
      { error: "Synthesis failed" },
      { status: response.status },
    );
  }

  const data = await response.json();
  return NextResponse.json(data);
}
