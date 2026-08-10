/**
 * usePipelineEvents hook tests — verifies stage-name alignment (V3),
 * stage status transitions, and reset-on-new-run behavior.
 */

import { renderHook, act } from "@testing-library/react";
import type { Socket } from "socket.io-client";

// We test the hook's internal logic by constructing a minimal socket stub
// that the hook can `.on("pipeline_stage", handler)` against.

// ── Helpers ─────────────────────────────────────────────────────────────────

interface StubSocket {
  listeners: Record<string, Array<(data: unknown) => void>>;
  on: jest.Mock;
  off: jest.Mock;
}

function createStubSocket(): StubSocket {
  const listeners: Record<string, Array<(data: unknown) => void>> = {};
  return {
    listeners,
    on: jest.fn((event: string, handler: (data: unknown) => void) => {
      if (!listeners[event]) listeners[event] = [];
      listeners[event].push(handler);
    }),
    off: jest.fn((event: string, handler: (data: unknown) => void) => {
      const arr = listeners[event];
      if (arr) {
        const idx = arr.indexOf(handler);
        if (idx !== -1) arr.splice(idx, 1);
      }
    }),
  };
}

function emit(socket: StubSocket, event: string, data: unknown): void {
  const handlers = socket.listeners[event] || [];
  for (const h of handlers) {
    h(data);
  }
}

// ── Dynamic import because the hook uses `use client`───────────────────────
// We import the module that exports the hook; in Jest with ESM, this works.

let usePipelineEvents: (socket: Socket) => {
  events: Array<{ stage: string; status: string; event_id: string }>;
  stageStatuses: Record<string, string>;
  isActive: boolean;
};

beforeAll(async () => {
  const mod = await import("../../hooks/usePipelineEvents");
  usePipelineEvents = mod.usePipelineEvents;
});

// ── Tests ───────────────────────────────────────────────────────────────────

describe("usePipelineEvents", () => {
  it("initializes all V3 stages as idle", () => {
    const stub = createStubSocket();
    const { result } = renderHook(() =>
      usePipelineEvents(stub as unknown as Socket),
    );

    expect(result.current.stageStatuses.schema_validation).toBe("idle");
    expect(result.current.stageStatuses.deduplication).toBe("idle");
    expect(result.current.stageStatuses.ner_extraction).toBe("idle");
    expect(result.current.stageStatuses.entity_resolution).toBe("idle");
    expect(result.current.stageStatuses.graph_persistence).toBe("idle");
    expect(result.current.stageStatuses.alert_publishing).toBe("idle");
    expect(result.current.stageStatuses.pipeline_complete).toBe("idle");
    expect(result.current.isActive).toBe(false);
  });

  it("does NOT contain removed V2 stages", () => {
    const stub = createStubSocket();
    const { result } = renderHook(() =>
      usePipelineEvents(stub as unknown as Socket),
    );

    // V2 stages that were removed
    expect(result.current.stageStatuses.llm_extraction).toBeUndefined();
    expect(result.current.stageStatuses.grounding_validation).toBeUndefined();
    expect(result.current.stageStatuses.graphrag_index).toBeUndefined();
  });

  it("transitions ner_extraction to active then done", () => {
    const stub = createStubSocket();
    const { result } = renderHook(() =>
      usePipelineEvents(stub as unknown as Socket),
    );

    act(() => {
      emit(stub, "pipeline_stage", {
        event_id: "evt-1",
        tenant_id: "default",
        stage: "ner_extraction",
        status: "active",
        timestamp: new Date().toISOString(),
      });
    });

    expect(result.current.stageStatuses.ner_extraction).toBe("active");
    expect(result.current.isActive).toBe(true);

    act(() => {
      emit(stub, "pipeline_stage", {
        event_id: "evt-1",
        tenant_id: "default",
        stage: "ner_extraction",
        status: "done",
        timestamp: new Date().toISOString(),
      });
    });

    expect(result.current.stageStatuses.ner_extraction).toBe("done");
  });

  it("resets all stages to idle when schema_validation becomes active", () => {
    const stub = createStubSocket();
    const { result } = renderHook(() =>
      usePipelineEvents(stub as unknown as Socket),
    );

    // First, get some stages to "done"
    act(() => {
      emit(stub, "pipeline_stage", {
        event_id: "evt-1",
        tenant_id: "default",
        stage: "schema_validation",
        status: "active",
        timestamp: new Date().toISOString(),
      });
      emit(stub, "pipeline_stage", {
        event_id: "evt-1",
        tenant_id: "default",
        stage: "schema_validation",
        status: "done",
        timestamp: new Date().toISOString(),
      });
      emit(stub, "pipeline_stage", {
        event_id: "evt-1",
        tenant_id: "default",
        stage: "ner_extraction",
        status: "done",
        timestamp: new Date().toISOString(),
      });
    });

    expect(result.current.stageStatuses.schema_validation).toBe("done");
    expect(result.current.stageStatuses.ner_extraction).toBe("done");

    // New pipeline run starts
    act(() => {
      emit(stub, "pipeline_stage", {
        event_id: "evt-2",
        tenant_id: "default",
        stage: "schema_validation",
        status: "active",
        timestamp: new Date().toISOString(),
      });
    });

    // All should be reset to idle except schema_validation (now active)
    expect(result.current.stageStatuses.schema_validation).toBe("active");
    expect(result.current.stageStatuses.ner_extraction).toBe("idle");
    expect(result.current.stageStatuses.deduplication).toBe("idle");
  });

  it("pipeline_complete transitions to done and sets isActive false", () => {
    const stub = createStubSocket();
    const { result } = renderHook(() =>
      usePipelineEvents(stub as unknown as Socket),
    );

    act(() => {
      emit(stub, "pipeline_stage", {
        event_id: "evt-1",
        tenant_id: "default",
        stage: "pipeline_complete",
        status: "done",
        timestamp: new Date().toISOString(),
      });
    });

    expect(result.current.stageStatuses.pipeline_complete).toBe("done");
    expect(result.current.isActive).toBe(false);
  });
});
