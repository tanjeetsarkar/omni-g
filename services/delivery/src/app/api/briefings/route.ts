/**
 * GET /api/briefings?tenant_id=X
 *
 * Proxies to PROCESSOR_URL/briefings?tenant_id=X.
 * On error: returns { briefings: [], error: "processor unavailable" }
 */

import { NextRequest, NextResponse } from "next/server";

const PROCESSOR_URL = process.env.PROCESSOR_URL ?? "http://localhost:8001";

export async function GET(req: NextRequest) {
  const tenantId = req.nextUrl.searchParams.get("tenant_id") ?? "default";

  try {
    const upstream = await fetch(
      `${PROCESSOR_URL}/briefings?tenant_id=${encodeURIComponent(tenantId)}`,
      { next: { revalidate: 0 } },
    );

    if (!upstream.ok) {
      throw new Error(`Upstream ${upstream.status}`);
    }

    const data = await upstream.json();
    return NextResponse.json(data);
  } catch {
    return NextResponse.json(
      { briefings: [], error: "processor unavailable" },
      { status: 200 },
    );
  }
}
