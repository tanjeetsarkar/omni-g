"use client";

/**
 * useSearchHistory — persists recent searches in sessionStorage.
 *
 * Stores last 10 searches as {query, timestamp, entityCount} objects.
 * Provides addSearch(), clearHistory(), getHistory().
 * Safe in Next.js client components (sessionStorage is client-only).
 */

import { useState, useCallback, useEffect } from "react";

export interface SearchHistoryEntry {
  query: string;
  timestamp: number;
  entityCount: number;
}

const STORAGE_KEY = "omni-g-search-history";
const MAX_ENTRIES = 10;

function loadHistory(): SearchHistoryEntry[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    return JSON.parse(raw) as SearchHistoryEntry[];
  } catch {
    return [];
  }
}

function saveHistory(entries: SearchHistoryEntry[]): void {
  if (typeof window === "undefined") return;
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(entries));
  } catch {
    // sessionStorage full or unavailable — silently ignore
  }
}

export function useSearchHistory() {
  const [history, setHistory] = useState<SearchHistoryEntry[]>([]);

  // Load on mount
  useEffect(() => {
    setHistory(loadHistory());
  }, []);

  const addSearch = useCallback((query: string, entityCount: number = 0) => {
    setHistory((prev) => {
      // Remove duplicate query if exists
      const filtered = prev.filter((e) => e.query !== query);
      const entry: SearchHistoryEntry = {
        query,
        timestamp: Date.now(),
        entityCount,
      };
      const updated = [entry, ...filtered].slice(0, MAX_ENTRIES);
      saveHistory(updated);
      return updated;
    });
  }, []);

  const clearHistory = useCallback(() => {
    setHistory([]);
    saveHistory([]);
  }, []);

  const getHistory = useCallback((): SearchHistoryEntry[] => {
    return history;
  }, [history]);

  return {
    history,
    addSearch,
    clearHistory,
    getHistory,
  };
}
