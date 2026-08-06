import { useEffect, useState, useCallback } from "react";
import type { Entity, Relationship } from "../types/entities";
import { getSocket } from "../lib/socket";

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
  const [newRelationships, setNewRelationships] = useState<Relationship[]>([]);

  const fetchEntities = useCallback(
    async (entityIds: string[]) => {
      if (entityIds.length === 0) return;
      try {
        // Use the direct entity-by-id endpoint — alerts carry canonical IDs
        // so we skip semantic search and go straight to Neo4j + neighbours.
        const res = await fetch("/api/entities", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            entity_ids: entityIds,
            tenant_id: tenantId,
          }),
        });
        if (!res.ok) return;
        const data: { entities?: Entity[]; relationships?: Relationship[] } =
          await res.json();
        if (data.entities && data.entities.length > 0) {
          setNewEntities((prev) => {
            const existingIds = new Set(prev.map((e) => e.id));
            const incoming = data.entities!.filter(
              (e) => !existingIds.has(e.id),
            );
            return incoming.length > 0 ? [...prev, ...incoming] : prev;
          });
        }
        if (data.relationships && data.relationships.length > 0) {
          setNewRelationships((prev) => {
            const existingIds = new Set(prev.map((r) => r.id));
            const incoming = data.relationships!.filter(
              (r) => !existingIds.has(r.id),
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

    // Reuse the shared socket singleton — avoids a second connection to the
    // gateway and ensures all event listeners share one subscription room.
    const socket = getSocket();

    const handleAlert = (payload: AlertPayload) => {
      const ids = payload.entity_ids ?? [];
      if (ids.length > 0) {
        fetchEntities(ids);
      }
    };

    socket.on("alert", handleAlert);

    return () => {
      socket.off("alert", handleAlert);
    };
  }, [enabled, fetchEntities]);

  const clearNewEntities = useCallback(() => {
    setNewEntities([]);
    setNewRelationships([]);
  }, []);

  return { newEntities, newRelationships, clearNewEntities };
}
