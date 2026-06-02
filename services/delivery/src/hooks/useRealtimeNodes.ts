import { useEffect, useState, useCallback } from "react";
import { io, type Socket } from "socket.io-client";
import type { Entity } from "../types/entities";

interface AlertPayload {
  entity_ids?: string[];
  summary?: string;
  [key: string]: unknown;
}

interface UseRealtimeNodesOptions {
  tenantId: string;
  enabled?: boolean;
}

export function useRealtimeNodes({
  tenantId,
  enabled = true,
}: UseRealtimeNodesOptions) {
  const [newEntities, setNewEntities] = useState<Entity[]>([]);

  const fetchEntities = useCallback(
    async (entityIds: string[]) => {
      if (entityIds.length === 0) return;
      try {
        const res = await fetch("/api/search", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            query: entityIds.join(" "),
            tenant_id: tenantId,
            limit: entityIds.length,
          }),
        });
        if (!res.ok) return;
        const data: { entities?: Entity[] } = await res.json();
        if (data.entities && data.entities.length > 0) {
          setNewEntities((prev) => {
            const existingIds = new Set(prev.map((e) => e.id));
            const incoming = data.entities!.filter(
              (e) => !existingIds.has(e.id),
            );
            return incoming.length > 0 ? [...prev, ...incoming] : prev;
          });
        }
      } catch {
        // silently ignore — real-time failures should not crash the UI
      }
    },
    [tenantId],
  );

  useEffect(() => {
    if (!enabled) return;

    const wsUrl = process.env.NEXT_PUBLIC_WS_URL ?? "http://localhost:3001";
    const socket: Socket = io(wsUrl, {
      reconnection: true,
      reconnectionDelay: 1000,
      reconnectionDelayMax: 5000,
      reconnectionAttempts: 5,
    });

    socket.on("connect", () => {
      socket.emit("subscribe", { tenant_id: tenantId });
    });

    socket.on("alert", (payload: AlertPayload) => {
      const ids = payload.entity_ids ?? [];
      if (ids.length > 0) {
        fetchEntities(ids);
      }
    });

    return () => {
      socket.disconnect();
    };
  }, [tenantId, enabled, fetchEntities]);

  const clearNewEntities = useCallback(() => setNewEntities([]), []);

  return { newEntities, clearNewEntities };
}
