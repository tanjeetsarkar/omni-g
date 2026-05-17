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
const KAFKA_BROKERS = (process.env.KAFKA_BROKERS ?? "localhost:9092").split(",");
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

io.on("connection", (socket) => {
  console.log(`[gateway] client connected: ${socket.id}`);
  connectedClients.inc();
  connectionLifecycle.inc({ event: "connect" });

  socket.on("join", ({ tenant_id }: { tenant_id: string }) => {
    if (!tenant_id) return;
    const room = `tenant:${tenant_id}`;
    socket.join(room);
    console.log(`[gateway] ${socket.id} joined room ${room}`);
  });

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
  entity_ids?: string[];
  severity?: string;
  message?: string;
  timestamp?: number;
  [key: string]: unknown;
}

export function createKafkaConsumer(): Consumer {
  const kafka = new Kafka({
    clientId: "delivery-gateway",
    brokers: KAFKA_BROKERS,
    retry: { retries: 5 },
  });

  return kafka.consumer({ groupId: "delivery-gateway" });
}

async function startConsumer(consumer: Consumer): Promise<void> {
  await consumer.connect();
  await consumer.subscribe({
    topic: KAFKA_ALERTS_TOPIC,
    fromBeginning: false,
  });

  await consumer.run({
    autoCommit: true,
    eachMessage: async ({ message }) => {
      if (!message.value) return;

      let parsed: AlertMessage;
      try {
        parsed = JSON.parse(message.value.toString()) as AlertMessage;
      } catch {
        console.warn("[gateway] failed to parse Kafka message");
        return;
      }

      const room = `tenant:${parsed.tenant_id}`;

      // Measure broadcast latency from message timestamp
      if (parsed.timestamp) {
        const latency = Date.now() - parsed.timestamp;
        broadcastLatency.observe(latency);
      }

      io.to(room).emit("alert", parsed);
      console.log(`[gateway] broadcast to ${room}:`, parsed);
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
    console.log(`[gateway] Kafka consumer connected → topic: ${KAFKA_ALERTS_TOPIC}`);
  } catch (err) {
    console.error("[gateway] Kafka connection failed (will retry on reconnect):", err);
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
if (process.env.NODE_ENV !== "test" && process.env.JEST_WORKER_ID === undefined) {
  main().catch((err) => {
    console.error("[gateway] fatal error:", err);
    process.exit(1);
  });
}
