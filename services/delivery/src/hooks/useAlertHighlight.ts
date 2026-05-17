"use client";

/**
 * useAlertHighlight — subscribes to "alert" events on the Socket.io connection.
 *
 * Returns { highlightedNodeIds, alertCount } where:
 *   - highlightedNodeIds: Set of entity IDs currently highlighted (cleared after 3000ms)
 *   - alertCount: cumulative count of alerts received since mount
 */

import { useEffect, useRef, useState } from "react";
import type { Socket } from "socket.io-client";

export interface AlertPayload {
  tenant_id: string;
  entity_ids?: string[];
  severity?: string;
  message?: string;
  timestamp?: number;
}

export function useAlertHighlight(socket: Socket): {
  highlightedNodeIds: Set<string>;
  alertCount: number;
} {
  const [highlightedNodeIds, setHighlightedNodeIds] = useState<Set<string>>(new Set());
  const [alertCount, setAlertCount] = useState(0);

  // Track active timeout IDs so we can clear them on unmount
  const timeoutsRef = useRef<ReturnType<typeof setTimeout>[]>([]);

  useEffect(() => {
    function handleAlert(alert: AlertPayload) {
      const ids = alert.entity_ids ?? [];

      if (ids.length > 0) {
        setHighlightedNodeIds((prev) => {
          const next = new Set(prev);
          ids.forEach((id) => next.add(id));
          return next;
        });

        // Remove those IDs after 3 seconds
        const timer = setTimeout(() => {
          setHighlightedNodeIds((prev) => {
            const next = new Set(prev);
            ids.forEach((id) => next.delete(id));
            return next;
          });
        }, 3000);

        timeoutsRef.current.push(timer);
      }

      setAlertCount((c) => c + 1);
    }

    socket.on("alert", handleAlert);

    return () => {
      socket.off("alert", handleAlert);
      // Clear any pending timeouts
      timeoutsRef.current.forEach(clearTimeout);
      timeoutsRef.current = [];
    };
  }, [socket]);

  return { highlightedNodeIds, alertCount };
}
