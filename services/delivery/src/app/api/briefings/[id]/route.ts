/**
 * GET /api/briefings/[id]?tenant_id=X
 *
 * Proxies to PROCESSOR_URL/briefings/{id}?tenant_id=X.
 * Returns { signed_url: string } or 404.
 */

import { NextRequest, NextResponse } from "next/server";

const PROCESSOR_URL = process.env.PROCESSOR_URL ?? "http://localhost:8001";

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const tenantId = req.nextUrl.searchParams.get("tenant_id") ?? "default";

  try {
    const upstream = await fetch(
      `${PROCESSOR_URL}/briefings/${encodeURIComponent(id)}?tenant_id=${encodeURIComponent(tenantId)}`,
      { next: { revalidate: 0 } }
    );

    if (upstream.status === 404) {
      return NextResponse.json({ error: "Not found" }, { status: 404 });
    }

    if (!upstream.ok) {
      throw new Error(`Upstream ${upstream.status}`);
    }

    const data = await upstream.json();
    return NextResponse.json(data);
  } catch {
    return NextResponse.json(
      { error: "processor unavailable" },
      { status: 502 }
    );
  }
}
