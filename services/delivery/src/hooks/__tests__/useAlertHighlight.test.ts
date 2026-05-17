/**
 * useAlertHighlight hook tests
 *
 * Uses a mock Socket.io socket to simulate alert events.
 */

import { renderHook, act } from "@testing-library/react";
import type { Socket } from "socket.io-client";
import { useAlertHighlight } from "@/hooks/useAlertHighlight";

function createMockSocket(): Socket {
  const listeners: Record<string, ((...args: unknown[]) => void)[]> = {};

  return {
    on: jest.fn((event: string, handler: (...args: unknown[]) => void) => {
      listeners[event] = listeners[event] ?? [];
      listeners[event].push(handler);
    }),
    off: jest.fn((event: string, handler: (...args: unknown[]) => void) => {
      listeners[event] = (listeners[event] ?? []).filter((h) => h !== handler);
    }),
    emit: jest.fn((event: string, ...args: unknown[]) => {
      (listeners[event] ?? []).forEach((h) => h(...args));
    }),
    // expose for testing
    _trigger(event: string, payload: unknown) {
      (listeners[event] ?? []).forEach((h) => h(payload));
    },
  } as unknown as Socket & { _trigger(e: string, p: unknown): void };
}

describe("useAlertHighlight", () => {
  beforeEach(() => {
    jest.useFakeTimers();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it("starts with empty highlightedNodeIds and alertCount of 0", () => {
    const socket = createMockSocket();
    const { result } = renderHook(() => useAlertHighlight(socket));

    expect(result.current.highlightedNodeIds.size).toBe(0);
    expect(result.current.alertCount).toBe(0);
  });

  it("adds entity_ids to highlightedNodeIds on alert event", () => {
    const socket = createMockSocket() as Socket & {
      _trigger: (e: string, p: unknown) => void;
    };
    const { result } = renderHook(() => useAlertHighlight(socket));

    act(() => {
      socket._trigger("alert", {
        tenant_id: "alpha",
        entity_ids: ["node-1", "node-2"],
        severity: "critical",
      });
    });

    expect(result.current.highlightedNodeIds.has("node-1")).toBe(true);
    expect(result.current.highlightedNodeIds.has("node-2")).toBe(true);
    expect(result.current.alertCount).toBe(1);
  });

  it("increments alertCount on each alert", () => {
    const socket = createMockSocket() as Socket & {
      _trigger: (e: string, p: unknown) => void;
    };
    const { result } = renderHook(() => useAlertHighlight(socket));

    act(() => {
      socket._trigger("alert", { tenant_id: "alpha", entity_ids: ["n1"] });
      socket._trigger("alert", { tenant_id: "alpha", entity_ids: ["n2"] });
    });

    expect(result.current.alertCount).toBe(2);
  });

  it("removes entity_ids from highlightedNodeIds after 3000ms", () => {
    const socket = createMockSocket() as Socket & {
      _trigger: (e: string, p: unknown) => void;
    };
    const { result } = renderHook(() => useAlertHighlight(socket));

    act(() => {
      socket._trigger("alert", {
        tenant_id: "alpha",
        entity_ids: ["node-1"],
        severity: "high",
      });
    });

    expect(result.current.highlightedNodeIds.has("node-1")).toBe(true);

    act(() => {
      jest.advanceTimersByTime(3000);
    });

    expect(result.current.highlightedNodeIds.has("node-1")).toBe(false);
  });

  it("handles alert with no entity_ids without throwing", () => {
    const socket = createMockSocket() as Socket & {
      _trigger: (e: string, p: unknown) => void;
    };
    const { result } = renderHook(() => useAlertHighlight(socket));

    act(() => {
      socket._trigger("alert", { tenant_id: "alpha" });
    });

    expect(result.current.alertCount).toBe(1);
    expect(result.current.highlightedNodeIds.size).toBe(0);
  });

  it("unsubscribes from socket on unmount", () => {
    const socket = createMockSocket();
    const { unmount } = renderHook(() => useAlertHighlight(socket));

    unmount();

    expect(socket.off).toHaveBeenCalledWith("alert", expect.any(Function));
  });
});
