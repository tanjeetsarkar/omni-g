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
 *
 * B6: Reconnect BriefingPanel to graph flow.
 * - Fetches transcript and extracts entity names
 * - Entity names render as clickable chips below the audio player
 * - Clicking a chip navigates to /explorer?q=entityName
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

interface Briefing {
  id: string;
  date: string;
  title?: string;
}

interface BriefingsResponse {
  briefings: Briefing[];
  error?: string;
}

interface TranscriptResponse {
  id: string;
  text: string;
  entities: string[];
  date: string;
}

interface BriefingPanelProps {
  tenantId: string;
}

// Simple client-side entity extraction regex — matches title-cased names
// and known entity patterns from the transcript text.
const ENTITY_PATTERN = /\b([A-Z][a-zA-Z]{2,}(?:\s+[A-Z][a-zA-Z]{2,}){0,3})\b/g;

function extractEntitiesFromText(text: string): string[] {
  const matches = text.match(ENTITY_PATTERN) ?? [];
  // De-duplicate, filter obvious non-entities, limit to 10
  const unique = Array.from(new Set(matches))
    .filter(
      (m) =>
        m.length > 2 &&
        !/^(The|All|We|They|That|This|There|These|Those|And|But|For|From|With|When|While|During|Would|Could|Should|About|After|Before|Then|Just|Much|Many)$/.test(
          m,
        ),
    )
    .slice(0, 10);
  return unique;
}

export default function BriefingPanel({ tenantId }: BriefingPanelProps) {
  const router = useRouter();
  const [briefings, setBriefings] = useState<Briefing[]>([]);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [playingId, setPlayingId] = useState<string | null>(null);
  const [transcriptEntities, setTranscriptEntities] = useState<string[]>([]);
  const audioRef = useRef<HTMLAudioElement>(null);

  const fetchBriefings = useCallback(async () => {
    try {
      const res = await fetch(
        `/api/briefings?tenant_id=${encodeURIComponent(tenantId)}`,
      );
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
    setTranscriptEntities([]);
    try {
      const res = await fetch(
        `/api/briefings/${encodeURIComponent(briefingId)}?tenant_id=${encodeURIComponent(tenantId)}`,
      );
      if (!res.ok) throw new Error("Failed to get signed URL");
      const { signed_url } = await res.json();
      if (audioRef.current) {
        audioRef.current.src = signed_url;
        audioRef.current.play();
      }

      // ── B6: Fetch transcript for entity extraction ──
      try {
        const transcriptRes = await fetch(
          `/api/briefings/${encodeURIComponent(briefingId)}/transcript?tenant_id=${encodeURIComponent(tenantId)}`,
        );
        if (transcriptRes.ok) {
          const transcript: TranscriptResponse = await transcriptRes.json();
          setTranscriptEntities(
            transcript.entities && transcript.entities.length > 0
              ? transcript.entities
              : extractEntitiesFromText(transcript.text || ""),
          );
        }
      } catch {
        // Transcript unavailable — silently skip entity chips
      }
    } catch {
      setPlayingId(null);
    }
  }

  function handleEntityClick(entityName: string) {
    router.push(`/explorer?q=${encodeURIComponent(entityName)}`);
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
            <div key={i} className="h-10 bg-slate-700 rounded animate-pulse" />
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

      {/* ── B6: Entity chips from transcript ── */}
      {transcriptEntities.length > 0 && (
        <div className="space-y-2 border-t border-slate-700 pt-3">
          <h3 className="text-[10px] text-slate-500 uppercase tracking-wider font-semibold">
            Related Entities
          </h3>
          <div className="flex flex-wrap gap-1.5">
            {transcriptEntities.map((entity) => (
              <button
                key={entity}
                onClick={() => handleEntityClick(entity)}
                className="text-xs px-2 py-1 rounded bg-slate-800 hover:bg-indigo-900/50 hover:text-indigo-300 text-slate-400 border border-slate-700 transition-colors"
              >
                {entity}
              </button>
            ))}
          </div>
          <p className="text-[10px] text-slate-600">
            Click an entity to explore it in the graph
          </p>
        </div>
      )}
    </div>
  );
}
