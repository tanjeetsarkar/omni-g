"use client";

/**
 * BriefingPanel — lists audio briefings and allows playback (M5.3).
 *
 * Props: { tenantId: string }
 *
 * - Fetches /api/briefings?tenant_id=X on mount and every 5 min
 * - Each row: date + "Play" button
 * - On Play: fetches signed URL → plays in <audio> element
 * - Loading: skeleton placeholders
 * - Error: "Briefings unavailable" message
 */

import { useCallback, useEffect, useRef, useState } from "react";

interface Briefing {
  id: string;
  date: string;
  title?: string;
}

interface BriefingsResponse {
  briefings: Briefing[];
  error?: string;
}

interface BriefingPanelProps {
  tenantId: string;
}

export default function BriefingPanel({ tenantId }: BriefingPanelProps) {
  const [briefings, setBriefings] = useState<Briefing[]>([]);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [playingId, setPlayingId] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement>(null);

  const fetchBriefings = useCallback(async () => {
    try {
      const res = await fetch(`/api/briefings?tenant_id=${encodeURIComponent(tenantId)}`);
      const data: BriefingsResponse = await res.json();
      if (data.error && data.briefings.length === 0) {
        setFetchError(data.error);
      } else {
        setBriefings(data.briefings ?? []);
        setFetchError(null);
      }
    } catch {
      setFetchError("Briefings unavailable");
    } finally {
      setLoading(false);
    }
  }, [tenantId]);

  useEffect(() => {
    fetchBriefings();
    const interval = setInterval(fetchBriefings, 5 * 60 * 1000);
    return () => clearInterval(interval);
  }, [fetchBriefings]);

  async function handlePlay(briefingId: string) {
    setPlayingId(briefingId);
    try {
      const res = await fetch(
        `/api/briefings/${encodeURIComponent(briefingId)}?tenant_id=${encodeURIComponent(tenantId)}`
      );
      if (!res.ok) throw new Error("Failed to get signed URL");
      const { signed_url } = await res.json();
      if (audioRef.current) {
        audioRef.current.src = signed_url;
        audioRef.current.play();
      }
    } catch {
      setPlayingId(null);
    }
  }

  function formatDate(dateStr: string): string {
    try {
      return new Date(dateStr).toLocaleDateString("en-US", {
        year: "numeric",
        month: "short",
        day: "numeric",
      });
    } catch {
      return dateStr;
    }
  }

  return (
    <div className="bg-slate-900 rounded-lg p-4 space-y-3">
      <h2 className="text-sm font-semibold text-slate-200 uppercase tracking-wide">
        Audio Briefings
      </h2>

      {/* Hidden audio element */}
      <audio ref={audioRef} onEnded={() => setPlayingId(null)} />

      {loading && (
        <div className="space-y-2" aria-label="Loading briefings">
          {[1, 2, 3].map((i) => (
            <div
              key={i}
              className="h-10 bg-slate-700 rounded animate-pulse"
            />
          ))}
        </div>
      )}

      {!loading && fetchError && (
        <p className="text-red-400 text-sm">{fetchError}</p>
      )}

      {!loading && !fetchError && briefings.length === 0 && (
        <p className="text-slate-500 text-sm">No briefings available.</p>
      )}

      {!loading && !fetchError && briefings.length > 0 && (
        <ul className="space-y-2">
          {briefings.map((b) => (
            <li
              key={b.id}
              className="flex items-center justify-between bg-slate-800 rounded px-3 py-2"
            >
              <span className="text-slate-300 text-sm">
                {b.title ?? formatDate(b.date)}
              </span>
              <button
                onClick={() => handlePlay(b.id)}
                disabled={playingId === b.id}
                className="text-xs font-medium bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-600 text-white px-3 py-1 rounded transition-colors"
              >
                {playingId === b.id ? "Playing…" : "Play"}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
