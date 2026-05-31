/**
 * gateway/__tests__/server.test.ts
 * @jest-environment node
 */

jest.mock("prom-client", () => {
  const gauges: Array<{
    __config: Record<string, unknown>;
    inc: jest.Mock;
    dec: jest.Mock;
    set: jest.Mock;
  }> = [];
  const histograms: Array<{
    __config: Record<string, unknown>;
    observe: jest.Mock;
  }> = [];
  const counters: Array<{
    __config: Record<string, unknown>;
    inc: jest.Mock;
  }> = [];

  return {
    Registry: jest.fn().mockImplementation(() => ({
      contentType: "text/plain",
      metrics: jest.fn().mockResolvedValue(""),
    })),
    Gauge: jest.fn().mockImplementation((config: Record<string, unknown>) => {
      const instance = {
        __config: config,
        inc: jest.fn(),
        dec: jest.fn(),
        set: jest.fn(),
      };
      gauges.push(instance);
      return instance;
    }),
    Histogram: jest
      .fn()
      .mockImplementation((config: Record<string, unknown>) => {
        const instance = {
          __config: config,
          observe: jest.fn(),
        };
        histograms.push(instance);
        return instance;
      }),
    Counter: jest.fn().mockImplementation((config: Record<string, unknown>) => {
      const instance = {
        __config: config,
        inc: jest.fn(),
      };
      counters.push(instance);
      return instance;
    }),
    collectDefaultMetrics: jest.fn(),
    __mock: { gauges, histograms, counters },
  };
});

jest.mock("http", () => ({
  createServer: jest.fn().mockReturnValue({
    listen: jest.fn(),
    close: jest.fn(),
  }),
}));

jest.mock("socket.io", () => {
  const servers: Array<{
    on: jest.Mock;
    to: jest.Mock;
    close: jest.Mock;
    __handlers: Record<string, (...args: unknown[]) => void>;
    __emits: Array<{ room: string; event: string; payload: unknown }>;
  }> = [];

  return {
    Server: jest.fn().mockImplementation(() => {
      const handlers: Record<string, (...args: unknown[]) => void> = {};
      const emits: Array<{ room: string; event: string; payload: unknown }> =
        [];

      type ServerMock = {
        on: jest.Mock;
        to: jest.Mock;
        close: jest.Mock;
        __handlers: Record<string, (...args: unknown[]) => void>;
        __emits: Array<{ room: string; event: string; payload: unknown }>;
      };
      const server: ServerMock = {
        on: jest.fn(
          (
            event: string,
            handler: (...args: unknown[]) => void,
          ): ServerMock => {
            handlers[event] = handler;
            return server;
          },
        ),
        to: jest.fn((room: string) => ({
          emit: jest.fn((event: string, payload: unknown) => {
            emits.push({ room, event, payload });
          }),
        })),
        close: jest.fn(),
        __handlers: handlers,
        __emits: emits,
      };

      servers.push(server);
      return server;
    }),
    __mock: { servers },
  };
});

jest.mock("kafkajs", () => {
  let capturedEachMessage:
    | ((payload: {
        topic: string;
        partition: number;
        message: { value: Buffer | null };
      }) => Promise<void>)
    | null = null;

  const consumer = {
    connect: jest.fn().mockResolvedValue(undefined),
    subscribe: jest.fn().mockResolvedValue(undefined),
    run: jest
      .fn()
      .mockImplementation(
        async ({
          eachMessage,
        }: {
          eachMessage: (payload: {
            topic: string;
            partition: number;
            message: { value: Buffer | null };
          }) => Promise<void>;
        }) => {
          capturedEachMessage = eachMessage;
        },
      ),
    disconnect: jest.fn().mockResolvedValue(undefined),
  };

  return {
    Kafka: jest.fn().mockImplementation(() => ({
      consumer: jest.fn().mockReturnValue(consumer),
    })),
    __mock: {
      consumer,
      getCapturedEachMessage: () => capturedEachMessage,
      resetCapturedEachMessage: () => {
        capturedEachMessage = null;
      },
    },
  };
});

import { Kafka } from "kafkajs";
import {
  AlertMessage,
  createKafkaConsumer,
  handleKafkaMessageValue,
  io,
  parseAlert,
  parseTimestampMs,
  startConsumer,
} from "../server";

type MockSocket = {
  id: string;
  rooms: Set<string>;
  join: jest.Mock<void, [string]>;
  leave: jest.Mock<void, [string]>;
  on: jest.Mock;
  data?: {
    subscriptionRooms?: string[];
  };
  __handlers: Record<string, (...args: unknown[]) => void>;
};

function getPromMock() {
  return jest.requireMock("prom-client").__mock as {
    gauges: Array<{
      __config: Record<string, unknown>;
      inc: jest.Mock;
      dec: jest.Mock;
      set: jest.Mock;
    }>;
    histograms: Array<{
      __config: Record<string, unknown>;
      observe: jest.Mock;
    }>;
    counters: Array<{
      __config: Record<string, unknown>;
      inc: jest.Mock;
    }>;
  };
}

function getSocketServerMock() {
  return jest.requireMock("socket.io").__mock.servers[0] as {
    on: jest.Mock;
    to: jest.Mock;
    close: jest.Mock;
    __handlers: Record<string, (...args: unknown[]) => void>;
    __emits: Array<{ room: string; event: string; payload: unknown }>;
  };
}

function getKafkaMock() {
  return jest.requireMock("kafkajs").__mock as {
    consumer: {
      connect: jest.Mock;
      subscribe: jest.Mock;
      run: jest.Mock;
      disconnect: jest.Mock;
    };
    getCapturedEachMessage: () =>
      | ((payload: {
          topic: string;
          partition: number;
          message: { value: Buffer | null };
        }) => Promise<void>)
      | null;
    resetCapturedEachMessage: () => void;
  };
}

function getConnectionHandler() {
  return getSocketServerMock().__handlers.connection;
}

function createMockSocket(id = "socket-1"): MockSocket {
  const handlers: Record<string, (...args: unknown[]) => void> = {};
  const rooms = new Set([id]);

  const socket: MockSocket = {
    id,
    rooms,
    join: jest.fn((room: string) => {
      rooms.add(room);
    }),
    leave: jest.fn((room: string) => {
      rooms.delete(room);
    }),
    on: jest.fn((event: string, handler: (...args: unknown[]) => void) => {
      handlers[event] = handler;
      return socket;
    }),
    __handlers: handlers,
  };

  return socket;
}

function getGauge(name: string) {
  return getPromMock().gauges.find((metric) => metric.__config.name === name);
}

function getHistogram(name: string) {
  return getPromMock().histograms.find(
    (metric) => metric.__config.name === name,
  );
}

function getCounter(name: string) {
  return getPromMock().counters.find((metric) => metric.__config.name === name);
}

describe("WebSocket Gateway – M5.1 hardening", () => {
  const warnSpy = jest
    .spyOn(console, "warn")
    .mockImplementation(() => undefined);

  beforeEach(() => {
    warnSpy.mockClear();
    getSocketServerMock().to.mockClear();
    getSocketServerMock().__emits.length = 0;
    getKafkaMock().consumer.connect.mockClear();
    getKafkaMock().consumer.subscribe.mockClear();
    getKafkaMock().consumer.run.mockClear();
    getKafkaMock().consumer.disconnect.mockClear();
    getKafkaMock().resetCapturedEachMessage();

    getPromMock().gauges.forEach((metric) => {
      metric.inc.mockClear();
      metric.dec.mockClear();
      metric.set.mockClear();
    });
    getPromMock().histograms.forEach((metric) => {
      metric.observe.mockClear();
    });
    getPromMock().counters.forEach((metric) => {
      metric.inc.mockClear();
    });
  });

  afterAll(() => {
    warnSpy.mockRestore();
  });

  describe("Kafka consumer", () => {
    it("creates consumer with groupId delivery-gateway", () => {
      const consumer = createKafkaConsumer();

      expect(Kafka).toHaveBeenCalledWith(
        expect.objectContaining({ clientId: "delivery-gateway" }),
      );
      expect(consumer).toBeDefined();
    });

    it("subscribes to analyst-alerts topic", async () => {
      const consumer = createKafkaConsumer();

      await startConsumer(consumer);

      expect(getKafkaMock().consumer.connect).toHaveBeenCalled();
      expect(getKafkaMock().consumer.subscribe).toHaveBeenCalledWith(
        expect.objectContaining({
          topic: "analyst-alerts",
          fromBeginning: false,
        }),
      );
      expect(getKafkaMock().consumer.run).toHaveBeenCalled();
      expect(getKafkaMock().getCapturedEachMessage()).toEqual(
        expect.any(Function),
      );
    });
  });

  describe("alert validation", () => {
    it("accepts a valid alert with ISO timestamp", () => {
      const alert = parseAlert({
        tenant_id: "alpha",
        timestamp: "2026-05-19T12:34:56.000Z",
        severity: "high",
      });

      expect(alert).toEqual({
        tenant_id: "alpha",
        timestamp: "2026-05-19T12:34:56.000Z",
        severity: "high",
        entity_ids: undefined,
        community_id: undefined,
        message: undefined,
      });
    });

    it("accepts a valid alert with numeric timestamp", () => {
      const timestamp = Date.now();

      expect(
        parseAlert({
          tenant_id: "alpha",
          timestamp,
          entity_ids: ["entity-1"],
        }),
      ).toEqual({
        tenant_id: "alpha",
        timestamp,
        entity_ids: ["entity-1"],
        community_id: undefined,
        severity: undefined,
        message: undefined,
      });
    });

    it("rejects alerts missing tenant_id", () => {
      expect(parseAlert({ timestamp: Date.now() })).toBeNull();
      expect(warnSpy).toHaveBeenCalled();
      expect(
        getCounter("delivery_invalid_alerts_total")?.inc,
      ).toHaveBeenCalled();
    });

    it("rejects alerts with empty tenant_id", () => {
      expect(
        parseAlert({ tenant_id: "   ", timestamp: Date.now() }),
      ).toBeNull();
      expect(warnSpy).toHaveBeenCalled();
      expect(
        getCounter("delivery_invalid_alerts_total")?.inc,
      ).toHaveBeenCalled();
    });

    it("handles non-JSON Kafka messages", () => {
      handleKafkaMessageValue(Buffer.from("not json"));

      expect(warnSpy).toHaveBeenCalled();
      expect(io.to).not.toHaveBeenCalled();
      expect(
        getCounter("delivery_invalid_alerts_total")?.inc,
      ).toHaveBeenCalled();
    });
  });

  describe("subscription routing", () => {
    it("subscribe with only tenant_id joins the tenant room", () => {
      const socket = createMockSocket();

      getConnectionHandler()(socket);
      socket.__handlers.subscribe?.({ tenant_id: "alpha" });

      expect(socket.join).toHaveBeenCalledWith("tenant:alpha");
      expect(socket.rooms).toEqual(new Set(["socket-1", "tenant:alpha"]));
    });

    it("subscribe with community_id joins the community room", () => {
      const socket = createMockSocket();

      getConnectionHandler()(socket);
      socket.__handlers.subscribe?.({
        tenant_id: "alpha",
        community_id: "community-7",
      });

      expect(socket.join).toHaveBeenCalledWith("tenant:alpha");
      expect(socket.join).toHaveBeenCalledWith(
        "tenant:alpha:community:community-7",
      );
    });

    it("subscribe with severity joins the severity room", () => {
      const socket = createMockSocket();

      getConnectionHandler()(socket);
      socket.__handlers.subscribe?.({
        tenant_id: "alpha",
        severity: "critical",
      });

      expect(socket.join).toHaveBeenCalledWith("tenant:alpha");
      expect(socket.join).toHaveBeenCalledWith(
        "tenant:alpha:severity:critical",
      );
    });

    it("subscribe sends ack with rooms list", () => {
      const socket = createMockSocket();
      const ack = jest.fn();

      getConnectionHandler()(socket);
      socket.__handlers.subscribe?.(
        {
          tenant_id: "alpha",
          community_id: "community-7",
          severity: "critical",
        },
        ack,
      );

      expect(ack).toHaveBeenCalledWith({
        ok: true,
        rooms: [
          "socket-1",
          "tenant:alpha",
          "tenant:alpha:community:community-7",
          "tenant:alpha:severity:critical",
        ],
      });
    });

    it("subscribe replaces stale subscription-specific rooms", () => {
      const socket = createMockSocket();

      getConnectionHandler()(socket);
      socket.__handlers.subscribe?.({
        tenant_id: "alpha",
        community_id: "community-7",
        severity: "critical",
      });
      socket.join.mockClear();
      socket.leave.mockClear();

      socket.__handlers.subscribe?.({
        tenant_id: "alpha",
        severity: "high",
      });

      expect(socket.leave).toHaveBeenCalledWith(
        "tenant:alpha:community:community-7",
      );
      expect(socket.leave).toHaveBeenCalledWith(
        "tenant:alpha:severity:critical",
      );
      expect(socket.rooms).toEqual(
        new Set(["socket-1", "tenant:alpha", "tenant:alpha:severity:high"]),
      );
    });
  });

  describe("Kafka eachMessage routing", () => {
    it("broadcasts community alerts to tenant and community rooms", async () => {
      const consumer = createKafkaConsumer();
      const alert: AlertMessage = {
        tenant_id: "alpha",
        community_id: "c-1",
        timestamp: Date.now() - 100,
      };

      await startConsumer(consumer);
      await getKafkaMock().getCapturedEachMessage()?.({
        topic: "analyst-alerts",
        partition: 0,
        message: { value: Buffer.from(JSON.stringify(alert)) },
      });

      expect(io.to).toHaveBeenCalledWith("tenant:alpha");
      expect(io.to).toHaveBeenCalledWith("tenant:alpha:community:c-1");
      expect(getSocketServerMock().__emits).toEqual([
        { room: "tenant:alpha", event: "alert", payload: alert },
        {
          room: "tenant:alpha:community:c-1",
          event: "alert",
          payload: alert,
        },
      ]);
    });

    it("broadcasts alerts without community only to the tenant room", async () => {
      const consumer = createKafkaConsumer();
      const alert: AlertMessage = {
        tenant_id: "alpha",
        timestamp: Date.now() - 100,
      };

      await startConsumer(consumer);
      await getKafkaMock().getCapturedEachMessage()?.({
        topic: "analyst-alerts",
        partition: 0,
        message: { value: Buffer.from(JSON.stringify(alert)) },
      });

      expect(io.to).toHaveBeenCalledTimes(1);
      expect(io.to).toHaveBeenCalledWith("tenant:alpha");
    });

    it("broadcasts severity alerts to the severity room too", async () => {
      const consumer = createKafkaConsumer();
      const alert: AlertMessage = {
        tenant_id: "alpha",
        severity: "critical",
        timestamp: Date.now() - 100,
      };

      await startConsumer(consumer);
      await getKafkaMock().getCapturedEachMessage()?.({
        topic: "analyst-alerts",
        partition: 0,
        message: { value: Buffer.from(JSON.stringify(alert)) },
      });

      expect(io.to).toHaveBeenCalledWith("tenant:alpha");
      expect(io.to).toHaveBeenCalledWith("tenant:alpha:severity:critical");
    });

    it("skips broadcast for invalid alerts", async () => {
      const consumer = createKafkaConsumer();

      await startConsumer(consumer);
      await getKafkaMock().getCapturedEachMessage()?.({
        topic: "analyst-alerts",
        partition: 0,
        message: {
          value: Buffer.from(JSON.stringify({ timestamp: Date.now() - 100 })),
        },
      });

      expect(io.to).not.toHaveBeenCalled();
    });

    it("skips null Kafka values without throwing", async () => {
      const consumer = createKafkaConsumer();

      await startConsumer(consumer);

      await expect(
        getKafkaMock().getCapturedEachMessage()?.({
          topic: "analyst-alerts",
          partition: 0,
          message: { value: null },
        }),
      ).resolves.toBeUndefined();
    });
  });

  describe("timestamp handling", () => {
    it("parses ISO timestamps into milliseconds", () => {
      expect(parseTimestampMs("2026-05-19T12:34:56.000Z")).toBe(
        Date.parse("2026-05-19T12:34:56.000Z"),
      );
    });

    it("returns numeric timestamps unchanged", () => {
      expect(parseTimestampMs(123456789)).toBe(123456789);
    });

    it("observes reasonable latency for ISO timestamps", () => {
      handleKafkaMessageValue(
        Buffer.from(
          JSON.stringify({
            tenant_id: "alpha",
            timestamp: new Date(Date.now() - 250).toISOString(),
          }),
        ),
      );

      const observeArg = getHistogram("delivery_broadcast_latency_ms")?.observe
        .mock.calls[0]?.[0];

      expect(typeof observeArg).toBe("number");
      expect(Number.isNaN(observeArg)).toBe(false);
      expect(observeArg).toBeGreaterThanOrEqual(0);
    });

    it("observes reasonable latency for numeric timestamps", () => {
      handleKafkaMessageValue(
        Buffer.from(
          JSON.stringify({
            tenant_id: "alpha",
            timestamp: Date.now() - 250,
          }),
        ),
      );

      const observeArg = getHistogram("delivery_broadcast_latency_ms")?.observe
        .mock.calls[0]?.[0];

      expect(typeof observeArg).toBe("number");
      expect(Number.isNaN(observeArg)).toBe(false);
      expect(observeArg).toBeGreaterThanOrEqual(0);
    });
  });

  describe("metrics", () => {
    it("registers delivery_invalid_alerts_total", () => {
      expect(getCounter("delivery_invalid_alerts_total")).toBeDefined();
    });

    it("observes broadcast latency for valid alerts", () => {
      handleKafkaMessageValue(
        Buffer.from(
          JSON.stringify({
            tenant_id: "alpha",
            timestamp: Date.now() - 100,
          }),
        ),
      );

      expect(
        getHistogram("delivery_broadcast_latency_ms")?.observe,
      ).toHaveBeenCalled();
    });

    it("tracks connect and disconnect lifecycle events", () => {
      const socket = createMockSocket();

      getConnectionHandler()(socket);
      socket.__handlers.disconnect?.("transport close");

      expect(getGauge("delivery_connected_clients")?.inc).toHaveBeenCalled();
      expect(getGauge("delivery_connected_clients")?.dec).toHaveBeenCalled();
      expect(
        getCounter("delivery_connection_lifecycle_total")?.inc,
      ).toHaveBeenCalledWith({ event: "connect" });
      expect(
        getCounter("delivery_connection_lifecycle_total")?.inc,
      ).toHaveBeenCalledWith({ event: "disconnect" });
    });

    it("tracks subscribe lifecycle events", () => {
      const socket = createMockSocket();

      getConnectionHandler()(socket);
      socket.__handlers.subscribe?.({ tenant_id: "alpha" });

      expect(
        getCounter("delivery_connection_lifecycle_total")?.inc,
      ).toHaveBeenCalledWith({ event: "subscribe" });
    });
  });
});
