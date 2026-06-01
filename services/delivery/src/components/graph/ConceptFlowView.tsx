"use client";

/**
 * ConceptFlowView — Interactive 1-hop entity card canvas (M6 UX).
 *
 * Renders the focused STIX entity as a large centre card, with inbound
 * connections on the left and outbound connections on the right.  Curved
 * SVG bezier paths connect the cards with confidence-gated styling:
 *
 *   ≥ 0.80  → solid indigo   (#6366f1)
 *   0.50–0.80 → dashed amber  (#f59e0b, 4px dash)
 *   < 0.50  → dotted red     (#ef4444, 2px dot)
 *
 * Dynamic line rerouting: a ResizeObserver on the container fires a
 * useLayoutEffect that re-queries every card's getBoundingClientRect(),
 * keeping SVG paths locked to card edge ports on every viewport resize.
 *
 * Clicking "Focus →" on any neighbour card pivots that node into the
 * centre, enabling seamless web navigation of the local graph.
 */

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  AlertTriangle,
  Bug,
  Building,
  ChevronRight,
  Crosshair,
  MapPin,
  Shield,
  ShieldAlert,
  Skull,
  Workflow,
} from "lucide-react";
import type { ComponentType } from "react";

import type { GraphEdge, GraphNode } from "@/types/graph";

// ─── STIX type → Lucide icon ─────────────────────────────────────────────────

const STIX_ICONS: Record<
  string,
  ComponentType<{ size?: number; className?: string }>
> = {
  "threat-actor": Skull,
  malware: Bug,
  "attack-pattern": Workflow,
  campaign: ShieldAlert,
  identity: Building,
  tool: Crosshair,
  location: MapPin,
  vulnerability: AlertTriangle,
  indicator: Shield,
};

const STIX_BADGE: Record<string, string> = {
  "threat-actor": "bg-red-700 text-white",
  malware: "bg-orange-600 text-white",
  "attack-pattern": "bg-yellow-500 text-black",
  campaign: "bg-purple-600 text-white",
  identity: "bg-blue-600 text-white",
  tool: "bg-cyan-600 text-white",
  location: "bg-emerald-600 text-white",
  vulnerability: "bg-rose-600 text-white",
  indicator: "bg-pink-600 text-white",
};

// ─── Confidence → SVG path style ─────────────────────────────────────────────

interface EdgeStyle {
  stroke: string;
  strokeWidth: number;
  strokeDasharray?: string;
  markerId: string;
}

function edgeStyle(confidence?: number): EdgeStyle {
  if (confidence === undefined || confidence >= 0.8) {
    return { stroke: "#6366f1", strokeWidth: 2, markerId: "arr-indigo" };
  }
  if (confidence >= 0.5) {
    return {
      stroke: "#f59e0b",
      strokeWidth: 1.5,
      strokeDasharray: "4,4",
      markerId: "arr-amber",
    };
  }
  return {
    stroke: "#ef4444",
    strokeWidth: 1,
    strokeDasharray: "2,4",
    markerId: "arr-red",
  };
}

// ─── Internal types ───────────────────────────────────────────────────────────

interface PathInfo {
  d: string;
  edgeId: string;
  label?: string;
  midX: number;
  midY: number;
  style: EdgeStyle;
}

interface NeighborEntry {
  edge: GraphEdge;
  node: GraphNode;
}

// ─── Sub-components ───────────────────────────────────────────────────────────

interface FocusCardProps {
  node: GraphNode;
  cardRef: (el: HTMLDivElement | null) => void;
}

function FocusCard({ node, cardRef }: FocusCardProps) {
  const Icon = STIX_ICONS[node.stixType ?? ""] ?? AlertTriangle;
  const badge = STIX_BADGE[node.stixType ?? ""] ?? "bg-slate-600 text-white";
  const conf = node.confidence;
  const barColor =
    conf === undefined
      ? "#6366f1"
      : conf >= 0.8
        ? "#6366f1"
        : conf >= 0.5
          ? "#f59e0b"
          : "#ef4444";

  return (
    <div
      ref={cardRef}
      className="bg-slate-800 border-2 border-indigo-500/60 rounded-2xl p-5 shadow-2xl shadow-indigo-500/10 w-64 select-none"
    >
      {/* Header */}
      <div className="flex items-start gap-3 mb-4">
        <div className="w-11 h-11 rounded-xl bg-indigo-500/15 flex items-center justify-center shrink-0">
          <Icon size={22} className="text-indigo-400" />
        </div>
        <div className="min-w-0">
          <p className="text-slate-100 font-bold text-sm leading-snug break-words">
            {node.label}
          </p>
          {node.stixType && (
            <span
              className={`inline-block text-[10px] font-semibold px-1.5 py-0.5 rounded mt-1 ${badge}`}
            >
              {node.stixType}
            </span>
          )}
        </div>
      </div>

      {/* Confidence bar */}
      {conf != null && (
        <div className="mb-3">
          <div className="flex justify-between text-[10px] text-slate-400 mb-1">
            <span>Confidence</span>
            <span className="font-mono">{(conf * 100).toFixed(0)}%</span>
          </div>
          <div className="h-1.5 bg-slate-700 rounded-full overflow-hidden">
            <div
              className="h-full rounded-full transition-all"
              style={{ width: `${conf * 100}%`, backgroundColor: barColor }}
            />
          </div>
        </div>
      )}

      {/* Community summary */}
      {node.communitySummary && (
        <p className="text-slate-400 text-[11px] leading-relaxed line-clamp-5 mt-1">
          {node.communitySummary}
        </p>
      )}

      {/* Focus label */}
      <p className="text-indigo-400/50 text-[10px] uppercase tracking-widest mt-3 text-center">
        ● Focus Entity
      </p>
    </div>
  );
}

interface NeighborCardProps {
  node: GraphNode;
  cardRef: (el: HTMLDivElement | null) => void;
  onPivot: (nodeId: string) => void;
}

function NeighborCard({ node, cardRef, onPivot }: NeighborCardProps) {
  const Icon = STIX_ICONS[node.stixType ?? ""] ?? AlertTriangle;
  const badge = STIX_BADGE[node.stixType ?? ""] ?? "bg-slate-600 text-white";

  return (
    <div
      ref={cardRef}
      className="bg-slate-900/90 border border-slate-700 hover:border-slate-500 rounded-xl p-3 w-44 transition-colors group"
    >
      <div className="flex items-center gap-2 mb-1.5">
        <Icon size={13} className="text-slate-400 shrink-0" />
        <p className="text-slate-200 text-xs font-semibold truncate">
          {node.label}
        </p>
      </div>
      {node.stixType && (
        <span
          className={`inline-block text-[9px] font-semibold px-1 py-0.5 rounded mb-2 ${badge}`}
        >
          {node.stixType}
        </span>
      )}
      {node.confidence != null && (
        <div className="h-1 bg-slate-700 rounded-full overflow-hidden mb-2">
          <div
            className="h-full rounded-full"
            style={{
              width: `${node.confidence * 100}%`,
              backgroundColor:
                node.confidence >= 0.8
                  ? "#6366f1"
                  : node.confidence >= 0.5
                    ? "#f59e0b"
                    : "#ef4444",
            }}
          />
        </div>
      )}
      <button
        onClick={() => onPivot(node.id)}
        className="w-full flex items-center justify-center gap-1 text-[10px] text-indigo-400 hover:text-white hover:bg-indigo-600 rounded px-1 py-0.5 transition-colors"
        aria-label={`Focus on ${node.label}`}
      >
        Focus <ChevronRight size={10} />
      </button>
    </div>
  );
}

// ─── Legend ───────────────────────────────────────────────────────────────────

function ConfidenceLegend() {
  return (
    <div className="absolute bottom-3 left-3 bg-slate-900/90 border border-slate-700 rounded-lg p-2.5 text-[10px] text-slate-400 space-y-1 pointer-events-none">
      <p className="text-slate-300 font-semibold mb-1 uppercase tracking-wide">
        Confidence
      </p>
      <div className="flex items-center gap-2">
        <svg width="28" height="6">
          <line x1="0" y1="3" x2="28" y2="3" stroke="#6366f1" strokeWidth="2" />
        </svg>
        <span>≥ 80% — High</span>
      </div>
      <div className="flex items-center gap-2">
        <svg width="28" height="6">
          <line
            x1="0"
            y1="3"
            x2="28"
            y2="3"
            stroke="#f59e0b"
            strokeWidth="1.5"
            strokeDasharray="4,4"
          />
        </svg>
        <span>50–80% — Moderate</span>
      </div>
      <div className="flex items-center gap-2">
        <svg width="28" height="6">
          <line
            x1="0"
            y1="3"
            x2="28"
            y2="3"
            stroke="#ef4444"
            strokeWidth="1"
            strokeDasharray="2,4"
          />
        </svg>
        <span>&lt; 50% — Low</span>
      </div>
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export interface ConceptFlowViewProps {
  nodes: GraphNode[];
  edges: GraphEdge[];
  selectedNodeId?: string | null;
  onNodeClick?: (nodeId: string) => void;
  className?: string;
}

export default function ConceptFlowView({
  nodes,
  edges,
  selectedNodeId,
  onNodeClick,
  className,
}: ConceptFlowViewProps) {
  // Internal focus state — initialised from selectedNodeId prop
  const [focusId, setFocusId] = useState<string | null>(selectedNodeId ?? null);

  // Keep in sync if parent changes selection
  useEffect(() => {
    if (selectedNodeId) setFocusId(selectedNodeId);
  }, [selectedNodeId]);

  const containerRef = useRef<HTMLDivElement>(null);

  // Keyed refs: "<nodeId>:center" | "<nodeId>:left" | "<nodeId>:right"
  const cardRefs = useRef<Map<string, HTMLDivElement>>(new Map());

  const [paths, setPaths] = useState<PathInfo[]>([]);

  // SVG dimensions tracked to fill the container exactly
  const [svgSize, setSvgSize] = useState({ w: 0, h: 0 });

  // ── 1-hop neighbours — memoised for stable useCallback deps ────────────────

  const focusNode = useMemo(
    () => nodes.find((n) => n.id === focusId) ?? null,
    [nodes, focusId],
  );

  const inbound = useMemo<NeighborEntry[]>(
    () =>
      edges
        .filter((e) => e.target === focusId)
        .flatMap((e) => {
          const node = nodes.find((n) => n.id === e.source);
          return node ? [{ edge: e, node }] : [];
        }),
    [edges, nodes, focusId],
  );

  const outbound = useMemo<NeighborEntry[]>(
    () =>
      edges
        .filter((e) => e.source === focusId)
        .flatMap((e) => {
          const node = nodes.find((n) => n.id === e.target);
          return node ? [{ edge: e, node }] : [];
        }),
    [edges, nodes, focusId],
  );

  // Stable ref to recalcPaths so ResizeObserver can call it without stale closure
  const recalcRef = useRef<(() => void) | null>(null);

  // ── ResizeObserver — dynamic line rerouting ────────────────────────────────

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry) {
        setSvgSize({
          w: entry.contentRect.width,
          h: entry.contentRect.height,
        });
      }
      // Call recalc directly — avoids a state bump that would cause a re-render loop
      recalcRef.current?.();
    });

    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // ── Path recalculation ─────────────────────────────────────────────────────

  const recalcPaths = useCallback(() => {
    const container = containerRef.current;
    if (!container || !focusId) {
      setPaths([]);
      return;
    }

    const cr = container.getBoundingClientRect();
    const focusEl = cardRefs.current.get(`${focusId}:center`);
    if (!focusEl) {
      setPaths([]);
      return;
    }

    const fr = focusEl.getBoundingClientRect();
    // Centre-left and centre-right ports of the focus card (container-relative)
    const focusLeftX = fr.left - cr.left;
    const focusMidY = fr.top - cr.top + fr.height / 2;
    const focusRightX = fr.right - cr.left;

    const newPaths: PathInfo[] = [];

    // Inbound: neighbour right edge → focus left edge
    for (const { edge, node } of inbound) {
      const el = cardRefs.current.get(`${node.id}:left`);
      if (!el) continue;
      const r = el.getBoundingClientRect();
      const sx = r.right - cr.left;
      const sy = r.top - cr.top + r.height / 2;
      const ex = focusLeftX;
      const ey = focusMidY;
      const dx = Math.abs(ex - sx) * 0.55;
      const d = `M ${sx} ${sy} C ${sx + dx} ${sy}, ${ex - dx} ${ey}, ${ex} ${ey}`;
      newPaths.push({
        d,
        edgeId: edge.id,
        label: edge.label,
        midX: (sx + ex) / 2,
        midY: Math.min(sy, ey) + Math.abs(sy - ey) / 2 - 10,
        style: edgeStyle(edge.confidence),
      });
    }

    // Outbound: focus right edge → neighbour left edge
    for (const { edge, node } of outbound) {
      const el = cardRefs.current.get(`${node.id}:right`);
      if (!el) continue;
      const r = el.getBoundingClientRect();
      const sx = focusRightX;
      const sy = focusMidY;
      const ex = r.left - cr.left;
      const ey = r.top - cr.top + r.height / 2;
      const dx = Math.abs(ex - sx) * 0.55;
      const d = `M ${sx} ${sy} C ${sx + dx} ${sy}, ${ex - dx} ${ey}, ${ex} ${ey}`;
      newPaths.push({
        d,
        edgeId: edge.id,
        label: edge.label,
        midX: (sx + ex) / 2,
        midY: Math.min(sy, ey) + Math.abs(sy - ey) / 2 - 10,
        style: edgeStyle(edge.confidence),
      });
    }

    // Only update state when paths actually changed — prevents re-render loops
    setPaths((prev) => {
      if (
        prev.length === newPaths.length &&
        prev.every(
          (p, i) => p.d === newPaths[i].d && p.edgeId === newPaths[i].edgeId,
        )
      ) {
        return prev;
      }
      return newPaths;
    });
  }, [focusId, inbound, outbound]);

  // Keep the stable ref up to date so ResizeObserver can always call the latest version
  useEffect(() => {
    recalcRef.current = recalcPaths;
  });

  // Run once after mount and whenever data/focus changes (card positions settled after paint)
  useLayoutEffect(() => {
    recalcPaths();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusId, inbound, outbound]);

  // ── Pivot handler ──────────────────────────────────────────────────────────

  function handlePivot(nodeId: string) {
    setFocusId(nodeId);
    onNodeClick?.(nodeId);
  }

  // ── Empty state ────────────────────────────────────────────────────────────

  if (!focusNode) {
    return (
      <div
        className={`flex flex-col items-center justify-center w-full h-full gap-3 ${className ?? ""}`}
      >
        <ShieldAlert size={32} className="text-slate-600" />
        <p className="text-slate-500 text-sm text-center max-w-xs">
          Select a node in the{" "}
          <span className="text-indigo-400">Network Map</span> to explore its
          connections here.
        </p>
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className={`relative w-full h-full overflow-auto bg-slate-950 ${className ?? ""}`}
    >
      {/* ── SVG path overlay ───────────────────────────────────────────────── */}
      <svg
        className="absolute inset-0 pointer-events-none"
        style={{
          zIndex: 1,
          width: svgSize.w || "100%",
          height: svgSize.h || "100%",
        }}
        aria-hidden="true"
      >
        <defs>
          {(["indigo", "amber", "red"] as const).map((c) => {
            const fill =
              c === "indigo"
                ? "#6366f1"
                : c === "amber"
                  ? "#f59e0b"
                  : "#ef4444";
            return (
              <marker
                key={c}
                id={`arr-${c}`}
                markerWidth="7"
                markerHeight="5"
                refX="7"
                refY="2.5"
                orient="auto"
              >
                <polygon points="0 0, 7 2.5, 0 5" fill={fill} />
              </marker>
            );
          })}
        </defs>

        {paths.map((p) => (
          <g key={p.edgeId}>
            <path
              d={p.d}
              fill="none"
              stroke={p.style.stroke}
              strokeWidth={p.style.strokeWidth}
              strokeDasharray={p.style.strokeDasharray}
              markerEnd={`url(#${p.style.markerId})`}
              opacity={0.75}
            />
            {p.label && (
              <text
                x={p.midX}
                y={p.midY}
                textAnchor="middle"
                fontSize="9"
                fill={p.style.stroke}
                fontFamily="monospace"
                opacity={0.9}
              >
                {p.label}
              </text>
            )}
          </g>
        ))}
      </svg>

      {/* ── Card layout ────────────────────────────────────────────────────── */}
      <div
        className="relative grid gap-6 p-10 min-h-full items-center"
        style={{ gridTemplateColumns: "1fr auto 1fr", zIndex: 2 }}
      >
        {/* Left — inbound */}
        <div className="flex flex-col gap-4 items-end">
          {inbound.length === 0 ? (
            <p className="text-slate-700 text-xs italic">
              No inbound connections
            </p>
          ) : (
            inbound.map(({ node }) => (
              <NeighborCard
                key={node.id}
                node={node}
                onPivot={handlePivot}
                cardRef={(el) => {
                  if (el) cardRefs.current.set(`${node.id}:left`, el);
                  else cardRefs.current.delete(`${node.id}:left`);
                }}
              />
            ))
          )}
        </div>

        {/* Centre — focus */}
        <div className="flex justify-center">
          <FocusCard
            node={focusNode}
            cardRef={(el) => {
              if (el) cardRefs.current.set(`${focusId}:center`, el);
              else cardRefs.current.delete(`${focusId}:center`);
            }}
          />
        </div>

        {/* Right — outbound */}
        <div className="flex flex-col gap-4 items-start">
          {outbound.length === 0 ? (
            <p className="text-slate-700 text-xs italic">
              No outbound connections
            </p>
          ) : (
            outbound.map(({ node }) => (
              <NeighborCard
                key={node.id}
                node={node}
                onPivot={handlePivot}
                cardRef={(el) => {
                  if (el) cardRefs.current.set(`${node.id}:right`, el);
                  else cardRefs.current.delete(`${node.id}:right`);
                }}
              />
            ))
          )}
        </div>
      </div>

      {/* ── Legend overlay ─────────────────────────────────────────────────── */}
      <ConfidenceLegend />
    </div>
  );
}
