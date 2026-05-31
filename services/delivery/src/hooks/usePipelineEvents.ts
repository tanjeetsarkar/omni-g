"use client";

/**
 * usePipelineEvents — subscribes to "pipeline_stage" events on the Socket.io connection.
 *
 * Returns a live view of processor pipeline activity for the current tenant:
 *   - events: last 100 stage events received, newest-first
 *   - stageStatuses: current status of each known pipeline stage
 *   - isActive: whether any stage is currently in-progress
 *
 * When schema_validation transitions to "active", all stage statuses reset to
 * "idle" so the progress bar cleanly represents the new pipeline run.
 */

import { useEffect, useRef, useState } from "react";
import type { Socket } from "socket.io-client";

export interface PipelineEvent {
  event_id: string;
  tenant_id: string;
  stage: string;
  status: "active" | "done";
  timestamp: string;
  /** Local epoch ms when this event was received by the client. */
  receivedAt: number;
}

export type StageStatus = "idle" | "active" | "done";

const MAX_EVENTS = 100;

const PIPELINE_STAGES = [
  "schema_validation",
  "deduplication",
  "llm_extraction",
  "entity_resolution",
  "graph_persistence",
  "graphrag_index",
  "alert_publishing",
] as const;

function initialStageStatuses(): Record<string, StageStatus> {
  return Object.fromEntries(PIPELINE_STAGES.map((s) => [s, "idle"]));
}

export function usePipelineEvents(socket: Socket): {
  events: PipelineEvent[];
  stageStatuses: Record<string, StageStatus>;
  isActive: boolean;
} {
  const [events, setEvents] = useState<PipelineEvent[]>([]);
  const [stageStatuses, setStageStatuses] =
    useState<Record<string, StageStatus>>(initialStageStatuses);

  // Prevent stale-closure issues inside the event handler
  const stageStatusesRef = useRef<Record<string, StageStatus>>(
    initialStageStatuses(),
  );

  useEffect(() => {
    function handlePipelineStage(raw: unknown) {
      if (!raw || typeof raw !== "object" || Array.isArray(raw)) return;

      const ev = raw as Record<string, unknown>;
      if (
        typeof ev.stage !== "string" ||
        (ev.status !== "active" && ev.status !== "done")
      )
        return;

      const stage = ev.stage;
      const status = ev.status as "active" | "done";

      const pipelineEvent: PipelineEvent = {
        event_id: typeof ev.event_id === "string" ? ev.event_id : "",
        tenant_id: typeof ev.tenant_id === "string" ? ev.tenant_id : "",
        stage,
        status,
        timestamp: typeof ev.timestamp === "string" ? ev.timestamp : "",
        receivedAt: Date.now(),
      };

      // Prepend to event log (newest first), cap at MAX_EVENTS.
      setEvents((prev) => [pipelineEvent, ...prev].slice(0, MAX_EVENTS));

      // When a new run starts, reset all stage statuses to "idle".
      let nextStatuses: Record<string, StageStatus>;
      if (stage === "schema_validation" && status === "active") {
        nextStatuses = initialStageStatuses();
      } else {
        nextStatuses = { ...stageStatusesRef.current };
      }

      nextStatuses[stage] = status;
      stageStatusesRef.current = nextStatuses;
      setStageStatuses(nextStatuses);
    }

    socket.on("pipeline_stage", handlePipelineStage);
    return () => {
      socket.off("pipeline_stage", handlePipelineStage);
    };
  }, [socket]);

  const isActive = Object.values(stageStatuses).some((s) => s === "active");

  return { events, stageStatuses, isActive };
}
