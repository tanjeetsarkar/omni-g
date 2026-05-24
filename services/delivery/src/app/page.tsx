"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import PipelineProgress from "@/components/PipelineProgress";

type Phase = "search" | "processing";

type SearchProgress = {
  search_id: string;
  events_queued: number;
  queued_by_source: Array<{
    source: string;
    blocks_queued: number;
  }>;
};

export default function Home() {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [phase, setPhase] = useState<Phase>("search");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [progress, setProgress] = useState<SearchProgress | null>(null);

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    const q = query.trim();
    if (!q) return;

    setSubmitting(true);
    setError(null);

    try {
      const res = await fetch("/api/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: q }),
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(`Search failed: ${text}`);
      }
      const data: SearchProgress = await res.json();
      setProgress(data);
      setPhase("processing");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setSubmitting(false);
    }
  }

  function handleReady() {
    router.push(`/dashboard?q=${encodeURIComponent(query.trim())}`);
  }

  return (
    <div className="min-h-screen bg-slate-950 flex items-center justify-center px-4">
      <div className="w-full max-w-lg">
        {phase === "search" && (
          <div className="text-center space-y-8">
            <div className="space-y-2">
              <h1 className="text-4xl font-bold text-slate-100 tracking-tight">
                Omni-G
              </h1>
              <p className="text-slate-400 text-base">
                Open-Source Intelligence Knowledge Graph
              </p>
            </div>

            <form onSubmit={handleSearch} className="flex gap-2">
              <input
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search an entity, person, or topic…"
                className="flex-1 bg-slate-900 border border-slate-700 text-slate-100
                           placeholder-slate-500 rounded-lg px-4 py-3 text-sm
                           focus:outline-none focus:border-indigo-500 focus:ring-1
                           focus:ring-indigo-500"
                autoFocus
              />
              <button
                type="submit"
                disabled={submitting || !query.trim()}
                className="bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-700
                           disabled:text-slate-500 text-white font-semibold px-5 py-3
                           rounded-lg transition-colors shrink-0"
              >
                {submitting ? "…" : "Search"}
              </button>
            </form>

            {error && <p className="text-red-400 text-sm">{error}</p>}

            <p className="text-slate-600 text-xs">
              Try: &quot;Sundar Pichai&quot;, &quot;Google&quot;,
              &quot;OpenAI&quot;
            </p>
          </div>
        )}

        {phase === "processing" && (
          <PipelineProgress
            query={query}
            progress={progress}
            onReady={handleReady}
          />
        )}
      </div>
    </div>
  );
}
