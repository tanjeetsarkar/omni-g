"use client";

/**
 * useSemanticZoom — listens to Sigma camera updates and reports zoom state.
 *
 * When the camera ratio exceeds `threshold`, the graph should collapse to
 * community clusters (isClustered = true).
 *
 * Usage:
 *   const { isClustered, zoomRatio } = useSemanticZoom(sigmaRef);
 */

import { useEffect, useState } from "react";
import type { RefObject } from "react";

// Minimal structural type — avoids a hard dependency on sigma's complex generics
// while remaining compatible with `useRef<Sigma | null>(null)` in the parent.
type SigmaLike = {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  on: (event: string, handler: (...args: any[]) => void) => void;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  off: (event: string, handler: (...args: any[]) => void) => void;
};

export function useSemanticZoom(
  sigmaRef: RefObject<SigmaLike | null>,
  threshold = 2.0,
): { isClustered: boolean; zoomRatio: number } {
  const [isClustered, setIsClustered] = useState(false);
  const [zoomRatio, setZoomRatio] = useState(1.0);

  useEffect(() => {
    const sigma = sigmaRef.current;
    if (!sigma) return;

    const handler = (camera: { ratio: number }) => {
      const ratio = camera.ratio;
      setZoomRatio(ratio);
      setIsClustered(ratio > threshold);
    };

    sigma.on("afterCameraUpdate", handler);
    return () => {
      sigma.off("afterCameraUpdate", handler);
    };
    // sigmaRef.current is intentionally in the dependency array:
    // the parent triggers a re-render (via setSigmaReady) after Sigma initialises,
    // which causes this effect to re-run and register the listener.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sigmaRef.current, threshold]);

  return { isClustered, zoomRatio };
}
