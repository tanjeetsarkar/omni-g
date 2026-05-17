/**
 * Socket.io client singleton.
 *
 * Phase M5.1 will wire this to the actual WebSocket gateway running on
 * port 3001. This module exports a lazy-initialized client so components
 * can import it without triggering a connection on every render.
 */
import { io, type Socket } from "socket.io-client";

let socket: Socket | undefined;

export function getSocket(): Socket {
  if (socket) return socket;

  const wsUrl = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:3001";

  socket = io(wsUrl, {
    autoConnect: false, // connect explicitly via socket.connect()
    reconnectionAttempts: 5,
    reconnectionDelay: 1000,
    transports: ["websocket"],
  });

  return socket;
}

export function disconnectSocket(): void {
  if (socket?.connected) {
    socket.disconnect();
  }
  socket = undefined;
}

/**
 * joinTenant — connects (if needed) and emits "join" with the tenant ID.
 * The gateway will add the socket to room `tenant:{tenantId}`.
 */
export function joinTenant(tenantId: string): void {
  const s = getSocket();
  if (!s.connected) s.connect();
  s.emit("join", { tenant_id: tenantId });
}
