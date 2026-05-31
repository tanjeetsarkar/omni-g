/**
 * Socket.io client singleton.
 *
 * Phase M5.1 will wire this to the actual WebSocket gateway running on
 * port 3001. This module exports a lazy-initialized client so components
 * can import it without triggering a connection on every render.
 */
import { io, type Socket } from "socket.io-client";

let socket: Socket | undefined;
let currentSubscription: SubscriptionParams | null = null;

export interface SubscriptionParams {
  tenant_id: string;
  community_id?: string;
  severity?: string;
}

function handleSocketConnect(): void {
  if (socket && currentSubscription) {
    socket.emit("subscribe", currentSubscription);
  }
}

function bindSubscriptionHandler(s: Socket): void {
  s.off("connect", handleSocketConnect).on("connect", handleSocketConnect);
}

export function getSocket(): Socket {
  if (socket) return socket;

  const wsUrl = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:3001";

  socket = io(wsUrl, {
    autoConnect: false, // connect explicitly via socket.connect()
    reconnectionAttempts: 5,
    reconnectionDelay: 1000,
    transports: ["websocket"],
  });

  bindSubscriptionHandler(socket);

  return socket;
}

export function subscribe(params: SubscriptionParams): void {
  const s = getSocket();

  currentSubscription = params;
  bindSubscriptionHandler(s);

  if (!s.connected) {
    s.connect();
    return;
  }

  s.emit("subscribe", params, () => undefined);
}

export function getCurrentSubscription(): SubscriptionParams | null {
  return currentSubscription;
}

export function disconnectSocket(): void {
  if (socket?.connected) {
    socket.disconnect();
  }
  socket = undefined;
  currentSubscription = null;
}

/**
 * joinTenant — connects (if needed) and emits "join" with the tenant ID.
 * The gateway will add the socket to room `tenant:{tenantId}`.
 */
export function joinTenant(tenantId: string): void {
  subscribe({ tenant_id: tenantId });
}
