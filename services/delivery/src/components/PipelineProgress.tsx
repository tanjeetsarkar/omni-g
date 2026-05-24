"use client";

/**
 * PipelineProgress — shows real-time pipeline stage progress after a search.
 *
 * Stages are time-simulated (no Kafka instrumentation needed for M5).
 * WebSocket alert events act as the definitive "done" signal.
 */

import { useEffect, useRef, useState } from "react";
import { CheckCircle, Circle, Loader, AlertCircle } from "lucide-react";
import { getSocket, joinTenant } from "@/lib/socket";
import type { AlertPayload } from "@/hooks/useAlertHighlight";

interface Stage {
  id: number;
  label: string;
  detail: string;
  /** Seconds after search start before this stage becomes active. */
  activateAt: number;
  /** Seconds after search start before this stage is marked done (if no alert). */
  doneAt: number;
}

const STAGES: Stage[] = [
  {
    id: 1,
    label: "Fetching open sources",
    detail: "Wikipedia · Wikidata · News",
    activateAt: 0,
    doneAt: 5,
  },
  {
    id: 2,
    label: "Publishing to pipeline",
    detail: "Kafka raw-feed",
    activateAt: 3,
    doneAt: 8,
  },
  {
    id: 3,
    label: "Extracting entities with AI",
    detail: "STIX 2.1 identification",
    activateAt: 8,
    doneAt: 18,
  },
  {
    id: 4,
    label: "Writing to Knowledge Graph",
    detail: "Neo4j entity resolution",
    activateAt: 15,
    doneAt: 25,
  },
  {
    id: 5,
    label: "Building community insights",
    detail: "GraphRAG summaries",
    activateAt: 22,
    doneAt: 35,
  },
];

type StageStatus = "pending" | "active" | "done" | "error";

interface Props {
  query: string;
  onReady: () => void;
}

export default function PipelineProgress({ query, onReady }: Props) {
  const [statuses, setStatuses] = useState<StageStatus[]>(
    STAGES.map(() => "pending"),
  );
  const [done, setDone] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const startRef = useRef(Date.now());
  const doneRef = useRef(false);

  // Tick every second to update stage statuses via time simulation.
  useEffect(() => {
    const timer = setInterval(() => {
      const secs = (Date.now() - startRef.current) / 1000;
      setElapsed(Math.round(secs));

      if (!doneRef.current) {
        setStatuses(
          STAGES.map((s) => {
            if (secs >= s.doneAt) return "done";
            if (secs >= s.activateAt) return "active";
            return "pending";
          }),
        );
      }

      // Fallback: if no alert after 60s, show continue button.
      if (secs >= 60 && !doneRef.current) {
        doneRef.current = true;
        setStatuses(STAGES.map(() => "done"));
        setDone(true);
        clearInterval(timer);
      }
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  // WebSocket listener — real done signal.
  useEffect(() => {
    const socket = getSocket();
    const tenantId = process.env.NEXT_PUBLIC_TENANT_ID ?? "default";
    joinTenant(tenantId);

    function handleAlert(alert: AlertPayload) {
      if (doneRef.current) return;
      // Any alert after the search started means the pipeline produced output.
      const _ = alert; // alert data available if needed
      doneRef.current = true;
      setStatuses(STAGES.map(() => "done"));
      setDone(true);
    }

    socket.on("alert", handleAlert);
    return () => {
      socket.off("alert", handleAlert);
    };
  }, []);

  return (
    <div className="w-full max-w-lg mx-auto mt-10 space-y-6">
      <p className="text-slate-400 text-sm text-center">
        Processing{" "}
        <span className="text-slate-200 font-medium">&quot;{query}&quot;</span>
        {!done && <span className="text-slate-500 ml-2">({elapsed}s)</span>}
      </p>

      <ol className="space-y-3">
        {STAGES.map((stage, i) => (
          <StageRow key={stage.id} stage={stage} status={statuses[i]} />
        ))}
      </ol>

      {done && (
        <div className="text-center pt-4">
          <button
            onClick={onReady}
            className="bg-indigo-600 hover:bg-indigo-500 text-white font-semibold
                       px-8 py-3 rounded-lg transition-colors"
          >
            Knowledge Graph ready →
          </button>
        </div>
      )}
    </div>
  );
}

function StageRow({ stage, status }: { stage: Stage; status: StageStatus }) {
  return (
    <li className="flex items-start gap-3">
      <StatusIcon status={status} />
      <div className="min-w-0">
        <p
          className={`text-sm font-medium ${
            status === "done"
              ? "text-slate-200"
              : status === "active"
                ? "text-indigo-400"
                : "text-slate-500"
          }`}
        >
          {stage.label}
        </p>
        <p className="text-xs text-slate-600">{stage.detail}</p>
      </div>
    </li>
  );
}

function StatusIcon({ status }: { status: StageStatus }) {
  switch (status) {
    case "done":
      return (
        <CheckCircle className="w-5 h-5 text-emerald-400 shrink-0 mt-0.5" />
      );
    case "active":
      return (
        <Loader className="w-5 h-5 text-indigo-400 shrink-0 mt-0.5 animate-spin" />
      );
    case "error":
      return <AlertCircle className="w-5 h-5 text-red-400 shrink-0 mt-0.5" />;
    default:
      return <Circle className="w-5 h-5 text-slate-700 shrink-0 mt-0.5" />;
  }
}
