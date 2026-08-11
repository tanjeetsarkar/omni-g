"use client";

import React, { useState, useCallback, KeyboardEvent } from "react";
import { Search, Loader2 } from "lucide-react";
import { useGraphExplorerStore } from "../../store/useGraphExplorerStore";

/**
 * V4 Track 1: top-center floating frosted-glass search pill.
 *
 * Enter triggers `store.executeQuery()` (graph retrieval via /api/query) and,
 * when an `onSubmit` callback is provided, also notifies the parent page so
 * it can fire the background /api/search ingestion trigger and manage the
 * pipeline progress toast + search history. The pill floats above the
 * ECharts canvas with a backdrop blur so the graph remains visible underneath.
 */
export function FloatingSearchBar({ onSubmit }: { onSubmit?: () => void }) {
  const query = useGraphExplorerStore((s) => s.query);
  const setQuery = useGraphExplorerStore((s) => s.setQuery);
  const executeQuery = useGraphExplorerStore((s) => s.executeQuery);
  const isLoading = useGraphExplorerStore((s) => s.isLoading);
  const [focused, setFocused] = useState(false);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Enter") {
        void executeQuery();
        onSubmit?.();
      }
    },
    [executeQuery, onSubmit],
  );

  return (
    <div className="absolute top-4 left-1/2 -translate-x-1/2 z-40 pointer-events-none">
      <div
        className={`pointer-events-auto flex items-center gap-2 pl-3 pr-2 py-2 rounded-full shadow-2xl backdrop-blur-md border transition-all w-[min(560px,90vw)] ${
          focused
            ? "bg-background/80 border-indigo-400/60 ring-2 ring-indigo-400/20"
            : "bg-background/70 border-slate-700/60"
        }`}
      >
        <Search
          size={16}
          className={focused ? "text-indigo-400" : "text-slate-400"}
        />
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={handleKeyDown}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          placeholder="Search entities, concepts, people…"
          className="flex-1 bg-transparent outline-none text-sm text-slate-100 placeholder:text-slate-500"
          aria-label="Search query"
        />
        {isLoading && (
          <Loader2
            size={16}
            className="text-indigo-400 animate-spin shrink-0"
          />
        )}
      </div>
    </div>
  );
}
