"use client";

import React, { useState, useCallback, useRef, useEffect } from "react";
import { Search, Loader2, Clock } from "lucide-react";
import { useGraphExplorerStore } from "../../store/useGraphExplorerStore";
import type { HistorySuggestion } from "../../types/entities";

/**
 * V4 Track 1: top-center floating frosted-glass search pill.
 *
 * V4 Phase 3: fuzzy history suggestions. As the user types (debounced 300ms),
 * we query `/api/query/history` for semantically similar past queries and
 * render a suggestion dropdown. Clicking a suggestion loads its cached result
 * instantly via the store's `executeQuery`.
 *
 * Enter triggers `store.executeQuery()` (graph retrieval via /api/query) and,
 * when an `onSubmit` callback is provided, also notifies the parent page so
 * it can fire the background /api/search ingestion trigger.
 */
export function FloatingSearchBar({ onSubmit }: { onSubmit?: () => void }) {
  const query = useGraphExplorerStore((s) => s.query);
  const setQuery = useGraphExplorerStore((s) => s.setQuery);
  const executeQuery = useGraphExplorerStore((s) => s.executeQuery);
  const isLoading = useGraphExplorerStore((s) => s.isLoading);
  const tenantId = useGraphExplorerStore((s) => s.tenantId);

  const [focused, setFocused] = useState(false);
  const [suggestions, setSuggestions] = useState<HistorySuggestion[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [searchingHistory, setSearchingHistory] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Debounced fuzzy-history lookup on query change.
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);

    const trimmed = query.trim();
    if (trimmed.length < 2) {
      setSuggestions([]);
      setShowSuggestions(false);
      return;
    }

    debounceRef.current = setTimeout(async () => {
      setSearchingHistory(true);
      try {
        const res = await fetch(
          `/api/query/history?q=${encodeURIComponent(trimmed)}&tenant_id=${encodeURIComponent(tenantId)}`,
        );
        if (res.ok) {
          const data = await res.json();
          const items: HistorySuggestion[] = data.suggestions ?? [];
          setSuggestions(items);
          setShowSuggestions(items.length > 0);
        }
      } catch {
        // History lookup failed — silently ignore (fuzzy suggestions are best-effort).
      } finally {
        setSearchingHistory(false);
      }
    }, 300);

    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [query, tenantId]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Enter") {
        setShowSuggestions(false);
        void executeQuery();
        onSubmit?.();
      }
      if (e.key === "Escape") {
        setShowSuggestions(false);
      }
    },
    [executeQuery, onSubmit],
  );

  const selectSuggestion = useCallback(
    (suggestion: HistorySuggestion) => {
      setQuery(suggestion.query_text);
      setShowSuggestions(false);
      // Load the cached result instantly via the store.
      void executeQuery();
      onSubmit?.();
    },
    [setQuery, executeQuery, onSubmit],
  );

  return (
    <div className="absolute top-4 left-1/2 -translate-x-1/2 z-40 pointer-events-none">
      <div className="relative">
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
            onFocus={() => {
              setFocused(true);
              if (suggestions.length > 0) setShowSuggestions(true);
            }}
            onBlur={() => setFocused(false)}
            placeholder="Search entities, concepts, people…"
            className="flex-1 bg-transparent outline-none text-sm text-slate-100 placeholder:text-slate-500"
            aria-label="Search query"
          />
          {(isLoading || searchingHistory) && (
            <Loader2
              size={16}
              className="text-indigo-400 animate-spin shrink-0"
            />
          )}
        </div>

        {/* ── V4 Phase 3: Fuzzy history suggestions dropdown ── */}
        {showSuggestions && suggestions.length > 0 && (
          <div className="pointer-events-auto absolute top-full mt-2 left-0 right-0 bg-slate-900/95 backdrop-blur-md border border-slate-700/60 rounded-xl shadow-2xl overflow-hidden">
            <div className="px-3 py-1.5 text-[10px] text-slate-500 uppercase tracking-wider font-semibold flex items-center gap-1.5 border-b border-slate-800/80">
              <Clock size={11} />
              Similar past searches
            </div>
            <ul className="max-h-64 overflow-y-auto py-1">
              {suggestions.map((s) => (
                <li key={s.search_id || s.query_text}>
                  <button
                    type="button"
                    onMouseDown={(e) => {
                      // Use onMouseDown so it fires before the input's onBlur.
                      e.preventDefault();
                      selectSuggestion(s);
                    }}
                    className="w-full text-left px-3 py-2 hover:bg-indigo-950/40 transition-colors flex items-center justify-between gap-2"
                  >
                    <div className="flex flex-col min-w-0">
                      <span className="text-sm text-slate-200 truncate">
                        {s.query_text}
                      </span>
                      <span className="text-[10px] text-slate-500">
                        {s.entity_count} entities ·{" "}
                        {Math.round(s.similarity_score * 100)}% match
                      </span>
                    </div>
                    <span className="text-[10px] text-indigo-400 shrink-0">
                      cached
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}
