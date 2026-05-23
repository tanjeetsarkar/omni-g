/**
 * useSemanticZoom hook tests
 *
 * Uses a locally-created mock Sigma instance to simulate camera update events.
 */

import { renderHook, act } from "@testing-library/react";
import { useSemanticZoom } from "../useSemanticZoom";

// Minimal mock that records listeners and can replay them
function createMockSigma() {
  const listeners: Record<string, ((...args: unknown[]) => void)[]> = {};

  return {
    on: jest.fn((event: string, cb: (...args: unknown[]) => void) => {
      listeners[event] = listeners[event] ?? [];
      listeners[event].push(cb);
    }),
    off: jest.fn((event: string, cb: (...args: unknown[]) => void) => {
      listeners[event] = (listeners[event] ?? []).filter((h) => h !== cb);
    }),
    emit(event: string, ...args: unknown[]) {
      (listeners[event] ?? []).forEach((h) => h(...args));
    },
  };
}

describe("useSemanticZoom", () => {
  it("returns isClustered=false and zoomRatio=1.0 when sigma ref is null", () => {
    const sigmaRef = { current: null };
    const { result } = renderHook(() => useSemanticZoom(sigmaRef));
    expect(result.current.isClustered).toBe(false);
    expect(result.current.zoomRatio).toBe(1.0);
  });

  it("registers afterCameraUpdate listener when sigma is set", () => {
    const sigma = createMockSigma();
    const sigmaRef = { current: sigma };
    renderHook(() => useSemanticZoom(sigmaRef));
    expect(sigma.on).toHaveBeenCalledWith(
      "afterCameraUpdate",
      expect.any(Function),
    );
  });

  it("sets isClustered=true when camera ratio exceeds default threshold (2.0)", () => {
    const sigma = createMockSigma();
    const sigmaRef = { current: sigma };
    const { result } = renderHook(() => useSemanticZoom(sigmaRef));

    act(() => {
      sigma.emit("afterCameraUpdate", { ratio: 3.0 });
    });

    expect(result.current.isClustered).toBe(true);
    expect(result.current.zoomRatio).toBe(3.0);
  });

  it("sets isClustered=false when camera ratio is below threshold", () => {
    const sigma = createMockSigma();
    const sigmaRef = { current: sigma };
    const { result } = renderHook(() => useSemanticZoom(sigmaRef));

    act(() => {
      sigma.emit("afterCameraUpdate", { ratio: 1.5 });
    });

    expect(result.current.isClustered).toBe(false);
    expect(result.current.zoomRatio).toBe(1.5);
  });

  it("respects a custom threshold", () => {
    const sigma = createMockSigma();
    const sigmaRef = { current: sigma };
    const { result } = renderHook(() => useSemanticZoom(sigmaRef, 1.5));

    act(() => {
      sigma.emit("afterCameraUpdate", { ratio: 2.0 });
    });

    expect(result.current.isClustered).toBe(true);
  });

  it("switches isClustered back to false when camera zooms back in", () => {
    const sigma = createMockSigma();
    const sigmaRef = { current: sigma };
    const { result } = renderHook(() => useSemanticZoom(sigmaRef));

    act(() => {
      sigma.emit("afterCameraUpdate", { ratio: 3.0 });
    });
    expect(result.current.isClustered).toBe(true);

    act(() => {
      sigma.emit("afterCameraUpdate", { ratio: 1.0 });
    });
    expect(result.current.isClustered).toBe(false);
  });

  it("deregisters the listener on unmount", () => {
    const sigma = createMockSigma();
    const sigmaRef = { current: sigma };
    const { unmount } = renderHook(() => useSemanticZoom(sigmaRef));

    unmount();

    expect(sigma.off).toHaveBeenCalledWith(
      "afterCameraUpdate",
      expect.any(Function),
    );
  });
});
