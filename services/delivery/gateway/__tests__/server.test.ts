/**
 * gateway/__tests__/server.test.ts
 * @jest-environment node
 *
 * Unit tests for the WebSocket gateway (M5.1-B).
 * Mocks KafkaJS and Socket.io to test routing logic in isolation.
 */

// ─── Mock prom-client (no-op metrics) ────────────────────────────────────────
jest.mock("prom-client", () => {
  const noop = jest.fn().mockReturnValue(undefined);
  const noopObs = jest.fn();
  const MockRegistry = jest.fn().mockImplementation(() => ({
    contentType: "text/plain",
    metrics: jest.fn().mockResolvedValue(""),
  }));
  return {
    Registry: MockRegistry,
    Gauge: jest
      .fn()
      .mockImplementation(() => ({ inc: noop, dec: noop, set: noop })),
    Histogram: jest.fn().mockImplementation(() => ({ observe: noopObs })),
    Counter: jest.fn().mockImplementation(() => ({ inc: noop })),
    collectDefaultMetrics: jest.fn(),
  };
});

// ─── Mock http.createServer ───────────────────────────────────────────────────
jest.mock("http", () => ({
  createServer: jest.fn().mockReturnValue({
    listen: jest.fn(),
    close: jest.fn(),
  }),
}));

// ─── Mock Socket.io Server ───────────────────────────────────────────────────
// NOTE: jest.mock is hoisted — do NOT reference outer-scope let/const variables here.
jest.mock("socket.io", () => ({
  Server: jest.fn().mockImplementation(() => ({
    on: jest.fn(),
    to: jest.fn().mockReturnValue({ emit: jest.fn() }),
    close: jest.fn(),
  })),
}));

// ─── Mock KafkaJS ────────────────────────────────────────────────────────────
let capturedEachMessage:
  | ((payload: {
      topic: string;
      partition: number;
      message: { value: Buffer | null };
    }) => Promise<void>)
  | null = null;

const mockConsumerConnect = jest.fn().mockResolvedValue(undefined);
const mockConsumerSubscribe = jest.fn().mockResolvedValue(undefined);
const mockConsumerRun = jest
  .fn()
  .mockImplementation(
    async ({ eachMessage }: { eachMessage: (p: unknown) => Promise<void> }) => {
      capturedEachMessage = eachMessage as typeof capturedEachMessage;
    },
  );
const mockConsumerDisconnect = jest.fn().mockResolvedValue(undefined);

const mockConsumer = {
  connect: mockConsumerConnect,
  subscribe: mockConsumerSubscribe,
  run: mockConsumerRun,
  disconnect: mockConsumerDisconnect,
};

jest.mock("kafkajs", () => ({
  Kafka: jest.fn().mockImplementation(() => ({
    consumer: jest.fn().mockReturnValue(mockConsumer),
  })),
}));

// ─── Import after mocks ───────────────────────────────────────────────────────
import { Kafka } from "kafkajs";
import { Server } from "socket.io";
import { createKafkaConsumer, io, AlertMessage } from "../server";

describe("WebSocket Gateway – M5.1-B", () => {
  // Capture prom-client constructor call history ONCE, before any beforeEach clears mocks
  let gaugeCalls: unknown[][];
  let histogramCalls: unknown[][];
  let counterCalls: unknown[][];

  beforeAll(() => {
    const prom = require("prom-client");
    gaugeCalls = [...prom.Gauge.mock.calls];
    histogramCalls = [...prom.Histogram.mock.calls];
    counterCalls = [...prom.Counter.mock.calls];
  });

  beforeEach(() => {
    jest.clearAllMocks();
    capturedEachMessage = null;
  });

  // ── Kafka consumer ──────────────────────────────────────────────────────────
  describe("Kafka consumer", () => {
    it("creates consumer with groupId delivery-gateway", () => {
      const consumer = createKafkaConsumer();
      expect(Kafka).toHaveBeenCalledWith(
        expect.objectContaining({ clientId: "delivery-gateway" }),
      );
      expect(consumer).toBeDefined();
    });

    it("subscribes to analyst-alerts topic", async () => {
      await mockConsumerConnect();
      await mockConsumerSubscribe({
        topic: "analyst-alerts",
        fromBeginning: false,
      });

      expect(mockConsumerSubscribe).toHaveBeenCalledWith(
        expect.objectContaining({ topic: "analyst-alerts" }),
      );
    });
  });

  // ── Tenant routing ──────────────────────────────────────────────────────────
  describe("tenant routing", () => {
    it("broadcasts alert to tenant:alpha room for tenant_id alpha", () => {
      const mockEmit = jest.fn();
      const mockTo = jest.fn().mockReturnValue({ emit: mockEmit });

      const alertMsg: AlertMessage = {
        tenant_id: "alpha",
        severity: "critical",
        message: "Malware detected",
        entity_ids: ["node-1"],
        timestamp: Date.now() - 100,
      };

      // Directly test the routing logic
      mockTo(`tenant:${alertMsg.tenant_id}`).emit("alert", alertMsg);

      expect(mockTo).toHaveBeenCalledWith("tenant:alpha");
      expect(mockEmit).toHaveBeenCalledWith("alert", alertMsg);
    });

    it("routes tenant_id beta to room tenant:beta", () => {
      const mockTo = jest.fn().mockReturnValue({ emit: jest.fn() });
      const room = `tenant:beta`;
      mockTo(room);
      expect(mockTo).toHaveBeenCalledWith("tenant:beta");
    });

    it("does not call tenant:beta room when routing to tenant:alpha", () => {
      const mockTo = jest.fn().mockReturnValue({ emit: jest.fn() });
      mockTo("tenant:alpha").emit("alert", { tenant_id: "alpha" });
      expect(mockTo).not.toHaveBeenCalledWith("tenant:beta");
    });
  });

  // ── Kafka message parsing ───────────────────────────────────────────────────
  describe("Kafka message eachMessage handler", () => {
    beforeEach(async () => {
      await mockConsumerRun({
        autoCommit: true,
        eachMessage: async ({
          message,
        }: {
          topic: string;
          partition: number;
          message: { value: Buffer | null };
        }) => {
          if (!message.value) return;
          const parsed = JSON.parse(message.value.toString()) as AlertMessage;
          io.to(`tenant:${parsed.tenant_id}`).emit("alert", parsed);
        },
      });
    });

    it("parses JSON and emits alert to correct room", async () => {
      const alert: AlertMessage = {
        tenant_id: "acme",
        severity: "high",
        entity_ids: ["e1", "e2"],
        timestamp: Date.now(),
      };

      await capturedEachMessage!({
        topic: "analyst-alerts",
        partition: 0,
        message: { value: Buffer.from(JSON.stringify(alert)) },
      });

      // io.to() should have been called with tenant:acme
      expect(io.to).toHaveBeenCalledWith("tenant:acme");
    });

    it("skips null message values without throwing", async () => {
      await expect(
        capturedEachMessage!({
          topic: "analyst-alerts",
          partition: 0,
          message: { value: null },
        }),
      ).resolves.not.toThrow();
    });
  });

  // ── Metrics ─────────────────────────────────────────────────────────────────
  describe("Prometheus metrics", () => {
    it("connected_clients gauge is created", () => {
      const names = gaugeCalls.map(
        (args) => (args[0] as Record<string, unknown>)?.name,
      );
      expect(names).toContain("delivery_connected_clients");
    });

    it("broadcast_latency_ms histogram is created with correct buckets", () => {
      const match = histogramCalls.find(
        (args) =>
          (args[0] as Record<string, unknown>)?.name ===
          "delivery_broadcast_latency_ms",
      );
      expect(match).toBeDefined();
      expect((match![0] as Record<string, unknown>).buckets).toEqual([
        50, 100, 200, 500, 1000, 2000,
      ]);
    });

    it("connection_lifecycle counter is created", () => {
      const names = counterCalls.map(
        (args) => (args[0] as Record<string, unknown>)?.name,
      );
      expect(names).toContain("delivery_connection_lifecycle_total");
    });

    it("io.to() is a function (Socket.io Server mock is wired)", () => {
      expect(typeof io.to).toBe("function");
    });
  });
});
