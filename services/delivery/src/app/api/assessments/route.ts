import { NextRequest, NextResponse } from "next/server";
import type { AssessmentsResponse } from "@/types/assessment";

const PROCESSOR_URL = process.env.PROCESSOR_URL ?? "http://localhost:8001";

/**
 * GET /api/assessments
 *
 * Proxy to the Processor /assessments endpoint. Returns the latest assessments
 * for a given tenant (and optionally a specific KIQ).
 *
 * Query params:
 *   tenant_id  — required
 *   kiq_id     — optional; filter to a specific KIQ
 *   limit      — optional; max results (default 10)
 *
 * Gracefully returns { assessments: [] } when the Processor is unreachable so
 * the UI degrades rather than errors on startup.
 */
export async function GET(req: NextRequest): Promise<NextResponse> {
  const { searchParams } = req.nextUrl;
  const tenant_id = searchParams.get("tenant_id");
  const kiq_id = searchParams.get("kiq_id");
  const limit = searchParams.get("limit") ?? "10";

  if (!tenant_id) {
    return NextResponse.json(
      { error: "tenant_id is required" },
      { status: 400 },
    );
  }

  const upstream = new URL(`${PROCESSOR_URL}/assessments`);
  upstream.searchParams.set("tenant_id", tenant_id);
  if (kiq_id) upstream.searchParams.set("kiq_id", kiq_id);
  upstream.searchParams.set("limit", limit);

  try {
    const res = await fetch(upstream.toString(), {
      headers: { "Content-Type": "application/json" },
      // Short timeout — UI should not block waiting for Processor
      signal: AbortSignal.timeout(5_000),
    });

    if (!res.ok) {
      // Processor returned an error — return empty rather than propagating
      console.warn(
        `[api/assessments] Processor returned ${res.status}; falling back to empty`,
      );
      const empty: AssessmentsResponse = { assessments: [] };
      return NextResponse.json(empty);
    }

    const data: AssessmentsResponse = (await res.json()) as AssessmentsResponse;
    return NextResponse.json(data);
  } catch (err) {
    // Processor unreachable — return empty so the UI degrades gracefully
    console.warn("[api/assessments] Processor unreachable:", err);
    const empty: AssessmentsResponse = { assessments: [] };
    return NextResponse.json(empty);
  }
}
