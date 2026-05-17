/**
 * GET /api/graph — mock graph data (M5.2)
 *
 * Returns seeded fixture data: 20 nodes + 15 edges.
 * Real Neo4j wiring is M6 scope.
 */

import { NextResponse } from "next/server";
import type { GraphNode, GraphEdge } from "@/types/graph";

function rng(seed: number): () => number {
  let s = seed;
  return () => {
    s = (s * 1664525 + 1013904223) & 0xffffffff;
    return (s >>> 0) / 0xffffffff;
  };
}

const rand = rng(42);

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

const COMMUNITIES = [
  "APT group linked to state-sponsored operations targeting financial institutions.",
  "Commodity malware family distributed via phishing campaigns.",
  "Infrastructure used in credential-harvesting operations.",
  "Threat cluster targeting critical energy sector.",
] as const;

const nodeFixtures: GraphNode[] = [
  { id: "n1",  label: "Emotet",             stixType: "malware" },
  { id: "n2",  label: "APT28",              stixType: "threat-actor" },
  { id: "n3",  label: "Spear Phishing",     stixType: "attack-pattern" },
  { id: "n4",  label: "Operation Ghostnet", stixType: "campaign" },
  { id: "n5",  label: "MiniDuke",           stixType: "malware" },
  { id: "n6",  label: "CVE-2021-44228",     stixType: "vulnerability" },
  { id: "n7",  label: "Cobalt Strike",      stixType: "tool" },
  { id: "n8",  label: "Fancy Bear",         stixType: "threat-actor" },
  { id: "n9",  label: "ACME Corp",          stixType: "identity" },
  { id: "n10", label: "Moscow, Russia",     stixType: "location" },
  { id: "n11", label: "Log4Shell Exploit",  stixType: "attack-pattern" },
  { id: "n12", label: "DarkSide",           stixType: "malware" },
  { id: "n13", label: "REvil",              stixType: "threat-actor" },
  { id: "n14", label: "Colonial Pipeline",  stixType: "campaign" },
  { id: "n15", label: "Mimikatz",           stixType: "tool" },
  { id: "n16", label: "CVE-2022-30190",     stixType: "vulnerability" },
  { id: "n17", label: "North Korea (DPRK)", stixType: "location" },
  { id: "n18", label: "Lazarus Group",      stixType: "threat-actor" },
  { id: "n19", label: "WannaCry",           stixType: "malware" },
  { id: "n20", label: "SolarWinds Attack",  stixType: "campaign" },
].map((n, i) => ({
  ...n,
  x: Math.round(rand() * 500),
  y: Math.round(rand() * 500),
  size: 5 + Math.round(rand() * 10),
  color: STIX_COLORS[n.stixType!] ?? "#6366f1",
  confidence: parseFloat((0.5 + rand() * 0.5).toFixed(2)),
  communitySummary: COMMUNITIES[i % COMMUNITIES.length],
}));

const edgeFixtures: GraphEdge[] = [
  { id: "e1",  source: "n2",  target: "n3",  label: "uses" },
  { id: "e2",  source: "n2",  target: "n1",  label: "uses" },
  { id: "e3",  source: "n4",  target: "n2",  label: "attributed-to" },
  { id: "e4",  source: "n2",  target: "n9",  label: "targets" },
  { id: "e5",  source: "n5",  target: "n4",  label: "indicates" },
  { id: "e6",  source: "n11", target: "n6",  label: "uses" },
  { id: "e7",  source: "n8",  target: "n7",  label: "uses" },
  { id: "e8",  source: "n8",  target: "n2",  label: "related-to" },
  { id: "e9",  source: "n13", target: "n14", label: "attributed-to" },
  { id: "e10", source: "n12", target: "n14", label: "uses" },
  { id: "e11", source: "n15", target: "n13", label: "uses" },
  { id: "e12", source: "n18", target: "n17", label: "attributed-to" },
  { id: "e13", source: "n19", target: "n18", label: "attributed-to" },
  { id: "e14", source: "n20", target: "n9",  label: "targets" },
  { id: "e15", source: "n2",  target: "n10", label: "attributed-to" },
];

export async function GET() {
  return NextResponse.json({
    nodes: nodeFixtures,
    edges: edgeFixtures,
  });
}
