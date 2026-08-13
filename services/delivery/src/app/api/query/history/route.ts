import { NextRequest, NextResponse } from "next/server";
import type { HistorySearchResponse } from "../../../../types/entities";

/**
 * GET /api/query/history — fuzzy match the user's in-progress query against
 * past search queries and return similar ones with their cached search_ids.
 *
 * The UI can load these cached results instantly without re-executing the
 * full /search pipeline.
 *
 * Query params:
 *   q          — the partial query text (required)
 *   tenant_id  — the tenant (default "default")
 */

const PROCESSOR_URL = process.env.PROCESSOR_URL ?? "http://localhost:8001";

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const q = searchParams.get("q");
  const tenant_id = searchParams.get("tenant_id") ?? "default";

  if (!q || !q.trim()) {
    return NextResponse.json(
      { error: "q (query) is required" },
      { status: 400 },
    );
  }

  let response: Response;
  try {
    response = await fetch(`${PROCESSOR_URL}/query/history/search`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query: q.trim(),
        tenant_id,
        limit: 5,
      }),
    });
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Processor unreachable";
    return NextResponse.json({ error: msg }, { status: 502 });
  }

  if (!response.ok) {
    return NextResponse.json(
      { error: "History search failed" },
      { status: response.status },
    );
  }

  const data: HistorySearchResponse = await response.json();
  return NextResponse.json(data);
}
