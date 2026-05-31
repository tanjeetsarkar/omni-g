import { NextRequest, NextResponse } from "next/server";

const AGGREGATOR_URL = process.env.AGGREGATOR_URL ?? "http://localhost:8080";

export async function POST(req: NextRequest) {
  const body = await req.json();

  const upstream = await fetch(`${AGGREGATOR_URL}/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  const data = await upstream.json();
  return NextResponse.json(data, { status: upstream.status });
}
