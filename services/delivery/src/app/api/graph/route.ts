/**
 * GET /api/graph — live Neo4j Knowledge Graph data
 *
 * Queries STIXEntity nodes and their relationships for the requested tenant.
 * Falls back to empty arrays on Neo4j connection errors so the UI degrades
 * gracefully when the database is unavailable.
 *
 * Query param: ?tenant_id=<id>  (default: "dev-tenant")
 */

import { NextRequest, NextResponse } from "next/server";
import { isInt, type Integer } from "neo4j-driver";
import type { GraphNode, GraphEdge } from "@/types/graph";
import { getDriver } from "@/lib/neo4j";

/**
 * Coerce a Neo4j Integer object ({low, high}) to a plain JS number.
 * Floats and plain numbers pass through unchanged. Null/undefined → undefined.
 */
function toNum(val: unknown): number | undefined {
  if (val == null) return undefined;
  if (isInt(val)) return (val as Integer).toNumber();
  if (typeof val === "number") return val;
  return undefined;
}

const STIX_COLORS: Record<string, string> = {
  "threat-actor": "#ef4444",
  malware: "#f97316",
  "attack-pattern": "#eab308",
  campaign: "#a855f7",
  identity: "#3b82f6",
  tool: "#06b6d4",
  location: "#10b981",
  vulnerability: "#f43f5e",
};

function randomCoord() {
  return Math.round(Math.random() * 1000);
}

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const tenantId = searchParams.get("tenant_id") ?? "dev-tenant";

  try {
    const driver = getDriver();
    const session = driver.session({ defaultAccessMode: "READ" });

    try {
      const result = await session.run(
        `MATCH (n:STIXEntity {tenant_id: $t})
         OPTIONAL MATCH (n)-[r]->(m:STIXEntity {tenant_id: $t})
         RETURN n, r, m
         LIMIT 500`,
        { t: tenantId },
      );

      const nodeMap = new Map<string, GraphNode>();
      const edges: GraphEdge[] = [];

      for (const record of result.records) {
        const n = record.get("n");
        const r = record.get("r");
        const m = record.get("m");

        if (n) {
          const id: string = n.properties.id ?? n.identity.toString();
          if (!nodeMap.has(id)) {
            const stixType: string = n.properties.stix_type ?? "";
            nodeMap.set(id, {
              id,
              label: n.properties.name ?? n.properties.id ?? id,
              stixType,
              communityId: toNum(n.properties.community_id),
              communitySummary: n.properties.community_summary ?? undefined,
              confidence: toNum(n.properties.confidence),
              x: randomCoord(),
              y: randomCoord(),
              size: 6,
              color: STIX_COLORS[stixType] ?? "#6366f1",
            });
          }
        }

        if (m) {
          const id: string = m.properties.id ?? m.identity.toString();
          if (!nodeMap.has(id)) {
            const stixType: string = m.properties.stix_type ?? "";
            nodeMap.set(id, {
              id,
              label: m.properties.name ?? m.properties.id ?? id,
              stixType,
              communityId: toNum(m.properties.community_id),
              communitySummary: m.properties.community_summary ?? undefined,
              confidence: toNum(m.properties.confidence),
              x: randomCoord(),
              y: randomCoord(),
              size: 6,
              color: STIX_COLORS[stixType] ?? "#6366f1",
            });
          }
        }

        if (r) {
          const sourceId: string =
            record.get("n")?.properties.id ??
            record.get("n")?.identity.toString();
          const targetId: string =
            record.get("m")?.properties.id ??
            record.get("m")?.identity.toString();
          if (sourceId && targetId) {
            edges.push({
              id: r.identity.toString(),
              source: sourceId,
              target: targetId,
              label: r.type,
              confidence: toNum(r.properties?.confidence),
            });
          }
        }
      }

      return NextResponse.json({
        nodes: Array.from(nodeMap.values()),
        edges,
      });
    } finally {
      await session.close();
    }
  } catch (err) {
    console.error("Neo4j graph query error:", err);
    return NextResponse.json({ nodes: [], edges: [] });
  }
}
