import { NextRequest, NextResponse } from "next/server";

/**
 * GET /api/trending?tenant_id=X&limit=5 — proxy to Processor's /trending endpoint.
 *
 * Returns recently-added high-confidence entities for the empty state.
 */

const PROCESSOR_URL = process.env.PROCESSOR_URL ?? "http://localhost:8001";

export async function GET(request: NextRequest) {
  const params = request.nextUrl.searchParams;
  const tenant_id = params.get("tenant_id") ?? "default";
  const limit = params.get("limit") ?? "5";

  let response: Response;
  try {
    response = await fetch(
      `${PROCESSOR_URL}/trending?tenant_id=${encodeURIComponent(tenant_id)}&limit=${encodeURIComponent(limit)}`,
    );
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Processor unreachable";
    return NextResponse.json({ error: msg }, { status: 502 });
  }

  if (!response.ok) {
    return NextResponse.json(
      { error: "Trending fetch failed" },
      { status: response.status },
    );
  }

  const data = await response.json();
  return NextResponse.json(data);
}
