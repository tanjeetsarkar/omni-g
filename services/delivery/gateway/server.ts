/**
 * Omni-G Delivery – WebSocket Gateway (M5.1-B)
 *
 * Standalone Node.js process that:
 *   1. Consumes the `analyst-alerts` Kafka topic via KafkaJS
 *   2. Broadcasts alerts to Socket.io rooms keyed by tenant_id
 *   3. Exposes Prometheus metrics on METRICS_PORT (default 9464)
 *
 * Run: ts-node --project gateway/tsconfig.json gateway/server.ts
 */

import { createServer as createHttpServer } from "http";
import { Kafka, Consumer } from "kafkajs";
import { Server } from "socket.io";
import {
  Counter,
  Gauge,
  Histogram,
  Registry,
  collectDefaultMetrics,
} from "prom-client";

// ─── Environment ────────────────────────────────────────────────────────────
const GATEWAY_PORT = parseInt(process.env.GATEWAY_PORT ?? "3001", 10);
const METRICS_PORT = parseInt(process.env.METRICS_PORT ?? "9464", 10);
const KAFKA_BROKERS = (process.env.KAFKA_BROKERS ?? "localhost:9092").split(
  ",",
);
const KAFKA_ALERTS_TOPIC = process.env.KAFKA_ALERTS_TOPIC ?? "analyst-alerts";

// ─── Prometheus registry ─────────────────────────────────────────────────────
const registry = new Registry();
collectDefaultMetrics({ register: registry });

const connectedClients = new Gauge({
  name: "delivery_connected_clients",
  help: "Number of currently connected Socket.io clients",
  registers: [registry],
});

const broadcastLatency = new Histogram({
  name: "delivery_broadcast_latency_ms",
  help: "Latency from Kafka message timestamp to Socket.io broadcast (ms)",
  buckets: [50, 100, 200, 500, 1000, 2000],
  registers: [registry],
});

const connectionLifecycle = new Counter({
  name: "delivery_connection_lifecycle_total",
  help: "Total Socket.io connection lifecycle events",
  labelNames: ["event"] as const,
  registers: [registry],
});

// ─── Metrics HTTP server ─────────────────────────────────────────────────────
const metricsServer = createHttpServer(async (req, res) => {
  if (req.url === "/metrics" && req.method === "GET") {
    try {
      res.writeHead(200, { "Content-Type": registry.contentType });
      res.end(await registry.metrics());
    } catch (err) {
      res.writeHead(500);
      res.end(String(err));
    }
  } else {
    res.writeHead(404);
    res.end("Not found");
  }
});

metricsServer.listen(METRICS_PORT, () => {
  console.log(`[metrics] listening on :${METRICS_PORT}/metrics`);
});

// ─── Socket.io server ────────────────────────────────────────────────────────
const httpServer = createHttpServer();

export const io = new Server(httpServer, {
  cors: {
    origin: "*",
    methods: ["GET", "POST"],
  },
  pingTimeout: 60000,
  pingInterval: 30000,
});

connectedClients.set(0);

export interface SubscribeParams {
  tenant_id: string;
  community_id?: string;
  severity?: string;
}

export interface SubscribeAck {
  ok: true;
  rooms: string[];
}

type GatewaySocket = {
  id: string;
  join: (room: string) => void;
  leave?: (room: string) => void;
  on: (event: string, handler: (...args: unknown[]) => void) => void;
  rooms?: Set<string>;
  data?: {
    subscriptionRooms?: string[];
  };
};

function deriveSubscriptionRooms(params: SubscribeParams): string[] {
  const rooms = [`tenant:${params.tenant_id}`];

  if (params.community_id) {
    rooms.push(`tenant:${params.tenant_id}:community:${params.community_id}`);
  }

  if (params.severity) {
    rooms.push(`tenant:${params.tenant_id}:severity:${params.severity}`);
  }

  return rooms;
}

function setSubscriptionRooms(
  socket: GatewaySocket,
  params: SubscribeParams,
): string[] {
  const nextRooms = deriveSubscriptionRooms(params);
  const previousRooms = socket.data?.subscriptionRooms ?? [];

  previousRooms
    .filter((room) => !nextRooms.includes(room))
    .forEach((room) => socket.leave?.(room));

  nextRooms.forEach((room) => socket.join(room));
  socket.data = {
    ...(socket.data ?? {}),
    subscriptionRooms: nextRooms,
  };

  return socket.rooms ? [...socket.rooms] : [socket.id, ...nextRooms];
}

io.on("connection", (socket) => {
  console.log(`[gateway] client connected: ${socket.id}`);
  connectedClients.inc();
  connectionLifecycle.inc({ event: "connect" });

  socket.on("join", ({ tenant_id }: { tenant_id: string }) => {
    if (!tenant_id) return;
    setSubscriptionRooms(socket, { tenant_id });
    console.log(`[gateway] ${socket.id} joined room tenant:${tenant_id}`);
  });

  socket.on(
    "subscribe",
    (params: SubscribeParams, ack?: (response: SubscribeAck) => void) => {
      if (!params?.tenant_id) return;

      const rooms = setSubscriptionRooms(socket, params);
      connectionLifecycle.inc({ event: "subscribe" });

      console.log(`[gateway] ${socket.id} subscribed`, params);

      if (typeof ack === "function") {
        ack({ ok: true, rooms });
      }
    },
  );

  socket.on("disconnect", (reason) => {
    console.log(`[gateway] client disconnected: ${socket.id} (${reason})`);
    connectedClients.dec();
    connectionLifecycle.inc({ event: "disconnect" });
  });
});

httpServer.listen(GATEWAY_PORT, () => {
  console.log(`[gateway] Socket.io listening on :${GATEWAY_PORT}`);
});

// ─── Kafka consumer ──────────────────────────────────────────────────────────
export interface AlertMessage {
  tenant_id: string;
  timestamp: string | number;
  entity_ids?: string[];
  community_id?: string;
  severity?: string;
  message?: string;
  [key: string]: unknown;
}

const invalidAlerts = new Counter({
  name: "delivery_invalid_alerts_total",
  help: "Total Kafka messages that failed alert schema validation",
  registers: [registry],
});

function warnInvalidAlert(reason: string, raw: unknown): void {
  console.warn("[gateway] invalid alert payload", { reason, raw });
  invalidAlerts.inc();
}

export function parseAlert(raw: unknown): AlertMessage | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    warnInvalidAlert("payload must be an object", raw);
    return null;
  }

  const candidate = raw as Record<string, unknown>;

  if (
    typeof candidate.tenant_id !== "string" ||
    candidate.tenant_id.trim() === ""
  ) {
    warnInvalidAlert("tenant_id must be a non-empty string", raw);
    return null;
  }

  if (
    typeof candidate.timestamp !== "number" &&
    typeof candidate.timestamp !== "string"
  ) {
    warnInvalidAlert("timestamp must be a string or number", raw);
    return null;
  }

  if (
    typeof candidate.timestamp === "number" &&
    !Number.isFinite(candidate.timestamp)
  ) {
    warnInvalidAlert("timestamp number must be finite", raw);
    return null;
  }

  if (
    typeof candidate.timestamp === "string" &&
    (candidate.timestamp.trim() === "" ||
      Number.isNaN(Date.parse(candidate.timestamp)))
  ) {
    warnInvalidAlert("timestamp string must be parseable", raw);
    return null;
  }

  if (
    candidate.entity_ids !== undefined &&
    (!Array.isArray(candidate.entity_ids) ||
      candidate.entity_ids.some((value) => typeof value !== "string"))
  ) {
    warnInvalidAlert("entity_ids must be an array of strings", raw);
    return null;
  }

  if (
    candidate.community_id !== undefined &&
    typeof candidate.community_id !== "string"
  ) {
    warnInvalidAlert("community_id must be a string", raw);
    return null;
  }

  if (
    candidate.severity !== undefined &&
    typeof candidate.severity !== "string"
  ) {
    warnInvalidAlert("severity must be a string", raw);
    return null;
  }

  if (
    candidate.message !== undefined &&
    typeof candidate.message !== "string"
  ) {
    warnInvalidAlert("message must be a string", raw);
    return null;
  }

  return {
    ...candidate,
    tenant_id: candidate.tenant_id,
    timestamp: candidate.timestamp,
    entity_ids: candidate.entity_ids as string[] | undefined,
    community_id: candidate.community_id as string | undefined,
    severity: candidate.severity as string | undefined,
    message: candidate.message as string | undefined,
  };
}

export function parseTimestampMs(ts: string | number): number {
  if (typeof ts === "number") return ts;
  const ms = Date.parse(ts);
  return Number.isNaN(ms) ? Date.now() : ms;
}

function broadcastAlert(alert: AlertMessage): void {
  const rooms = [`tenant:${alert.tenant_id}`];

  if (alert.community_id) {
    rooms.push(`tenant:${alert.tenant_id}:community:${alert.community_id}`);
  }

  if (alert.severity) {
    rooms.push(`tenant:${alert.tenant_id}:severity:${alert.severity}`);
  }

  rooms.forEach((room) => {
    io.to(room).emit("alert", alert);
    console.log(`[gateway] broadcast to ${room}:`, alert);
  });
}

export function handleKafkaMessageValue(messageValue: Buffer | null): void {
  if (!messageValue) return;

  let raw: unknown;
  try {
    raw = JSON.parse(messageValue.toString()) as unknown;
  } catch {
    warnInvalidAlert("payload must be valid JSON", messageValue.toString());
    return;
  }

  const parsed = parseAlert(raw);
  if (!parsed) return;

  const latency = Date.now() - parseTimestampMs(parsed.timestamp);
  broadcastLatency.observe(latency);

  broadcastAlert(parsed);
}

export function createKafkaConsumer(): Consumer {
  const kafka = new Kafka({
    clientId: "delivery-gateway",
    brokers: KAFKA_BROKERS,
    retry: { retries: 5 },
  });

  return kafka.consumer({ groupId: "delivery-gateway" });
}

export async function startConsumer(consumer: Consumer): Promise<void> {
  await consumer.connect();
  await consumer.subscribe({
    topic: KAFKA_ALERTS_TOPIC,
    fromBeginning: false,
  });

  await consumer.run({
    autoCommit: true,
    eachMessage: async ({ message }) => {
      handleKafkaMessageValue(message.value);
    },
  });
}

// ─── Bootstrap ───────────────────────────────────────────────────────────────
// Only auto-start when NOT running under Jest
let consumer: Consumer | null = null;

async function main(): Promise<void> {
  consumer = createKafkaConsumer();
  try {
    await startConsumer(consumer);
    console.log(
      `[gateway] Kafka consumer connected → topic: ${KAFKA_ALERTS_TOPIC}`,
    );
  } catch (err) {
    console.error(
      "[gateway] Kafka connection failed (will retry on reconnect):",
      err,
    );
  }
}

// ─── Graceful shutdown ───────────────────────────────────────────────────────
async function shutdown(signal: string): Promise<void> {
  console.log(`[gateway] received ${signal}, shutting down…`);
  if (consumer) {
    try {
      await consumer.disconnect();
    } catch {
      // ignore
    }
  }
  io.close();
  metricsServer.close();
  process.exit(0);
}

process.on("SIGTERM", () => shutdown("SIGTERM"));
process.on("SIGINT", () => shutdown("SIGINT"));

// Only auto-start when NOT in Jest test environment
if (
  process.env.NODE_ENV !== "test" &&
  process.env.JEST_WORKER_ID === undefined
) {
  main().catch((err) => {
    console.error("[gateway] fatal error:", err);
    process.exit(1);
  });
}
