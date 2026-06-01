"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Search, Loader, ShieldAlert } from "lucide-react";

export default function Home() {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [submitting, setSubmitting] = useState(false);

  function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    const q = query.trim();
    if (!q || submitting) return;
    setSubmitting(true);
    // Navigate directly to the workspace — the dashboard handles ingestion inline.
    router.push(`/dashboard?q=${encodeURIComponent(q)}`);
  }

  return (
    <div className="min-h-screen bg-slate-950 flex items-center justify-center px-4">
      <div className="w-full max-w-lg text-center space-y-8">
        {/* Brand */}
        <div className="space-y-3">
          <div className="flex items-center justify-center gap-2 mb-2">
            <ShieldAlert size={28} className="text-indigo-400" />
          </div>
          <h1 className="text-4xl font-bold text-slate-100 tracking-tight">
            Omni-G
          </h1>
          <p className="text-slate-400 text-sm leading-relaxed">
            Open-Source Intelligence Knowledge Graph
            <br />
            <span className="text-slate-600 text-xs">
              Synthesis-centric · STIX 2.1 · Real-time
            </span>
          </p>
        </div>

        {/* Search form */}
        <form onSubmit={handleSearch} className="flex gap-2">
          <div className="relative flex-1">
            <Search
              size={14}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500 pointer-events-none"
            />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search an entity, person, or topic…"
              className="w-full bg-slate-900 border border-slate-700 text-slate-100
                         placeholder-slate-500 rounded-lg pl-9 pr-4 py-3 text-sm
                         focus:outline-none focus:border-indigo-500 focus:ring-1
                         focus:ring-indigo-500"
              autoFocus
              disabled={submitting}
            />
          </div>
          <button
            type="submit"
            disabled={submitting || !query.trim()}
            className="bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-700
                       disabled:text-slate-500 text-white font-semibold px-5 py-3
                       rounded-lg transition-colors shrink-0 flex items-center gap-1.5"
          >
            {submitting ? <Loader size={14} className="animate-spin" /> : null}
            {submitting ? "Opening…" : "Explore"}
          </button>
        </form>

        <p className="text-slate-600 text-xs">
          Try: &quot;Sundar Pichai&quot;, &quot;Google&quot;, &quot;OpenAI&quot;
        </p>

        {/* Skip to workspace */}
        <p className="text-slate-600 text-xs">
          or{" "}
          <button
            onClick={() => router.push("/dashboard")}
            className="text-indigo-500 hover:text-indigo-400 underline underline-offset-2 transition-colors"
          >
            open the workstation directly
          </button>
        </p>
      </div>
    </div>
  );
}
