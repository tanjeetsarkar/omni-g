"use client";

import { useEffect, useState } from "react";
import type { Socket } from "socket.io-client";
import type { Assessment } from "@/types/assessment";

/**
 * useAssessmentEvents — subscribes to `assessment_event` Socket.io events
 * from the delivery gateway and accumulates the latest assessment per KIQ.
 *
 * The gateway emits `assessment_event` whenever the Processor publishes an
 * `assessment.produced` record to the `assessments-produced` Kafka topic.
 */

interface UseAssessmentEventsOptions {
  socket: Socket;
}

interface UseAssessmentEventsResult {
  /** Latest assessment received (any KIQ), or null if none yet */
  latestAssessment: Assessment | null;
  /** Map of kiq_id → most recent Assessment for that KIQ */
  assessmentsByKiq: Map<string, Assessment>;
}

export function useAssessmentEvents({
  socket,
}: UseAssessmentEventsOptions): UseAssessmentEventsResult {
  const [latestAssessment, setLatestAssessment] = useState<Assessment | null>(
    null,
  );
  const [assessmentsByKiq, setAssessmentsByKiq] = useState<
    Map<string, Assessment>
  >(new Map());

  useEffect(() => {
    function handleAssessmentEvent(payload: unknown): void {
      if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
        return;
      }
      const assessment = payload as Assessment;
      if (
        typeof assessment.id !== "string" ||
        typeof assessment.kiq_id !== "string" ||
        typeof assessment.conclusion !== "string"
      ) {
        return;
      }

      setLatestAssessment(assessment);
      setAssessmentsByKiq((prev) => {
        const next = new Map(prev);
        const existing = next.get(assessment.kiq_id);
        // Keep the newest version (higher version number wins)
        if (!existing || assessment.version >= existing.version) {
          next.set(assessment.kiq_id, assessment);
        }
        return next;
      });
    }

    socket.on("assessment_event", handleAssessmentEvent);
    return () => {
      socket.off("assessment_event", handleAssessmentEvent);
    };
  }, [socket]);

  return { latestAssessment, assessmentsByKiq };
}
