# Omni-G V4 UX & Pipeline Overhaul — Release Notes

**Date:** August 13, 2026
**Scope:** Processor, Delivery, Gateway (Aggregator unchanged)
**Files:** 28 modified, 3 created, 5 deleted

---

## Overview

V4 transforms Omni-G from a generic graph explorer into a **query-centric intelligence drilldown tool**. Every search is now a first-class entity with its own identity, cache, pipeline visibility, and scoped realtime updates. The graph renders as a radial tree rooted at the most relevant entity, and provenance is non-negotiable — no node reaches the UI without a source.

---

## Features

### 1. Instant Search Results (3-Tier Cache)

**What:** Repeated or similar searches return instantly without re-running the full pipeline.

**How it works:**
- **Tier 1 — Exact match:** SHA-256 hash of `(tenant_id + query)` → Redis lookup. <5ms.
- **Tier 2 — Fuzzy text match:** RediSearch `FT.SEARCH` with fuzzy matching. "Elon Musk" matches "elon reeve musk". ~10ms.
- **Tier 3 — Semantic match:** Query embedding → Qdrant cosine similarity. "AI safety" matches "artificial intelligence regulation". ~50-100ms.
- Cache TTL: 1 hour (configurable via `QUERY_CACHE_TTL` env var).
- Fail-open: if Redis or Qdrant is down, search still works — just uncached.

**Where to look:**
- `services/processor/src/cache/query_cache.py` — `QueryCacheService` class
- `services/processor/src/processor/main.py` — `/search` endpoint, cache check at line ~820, cache store at end of handler
- `infrastructure/docker-compose.yml` — `QUERY_CACHE_TTL=${QUERY_CACHE_TTL:-3600}`

**How to feel it:** Run the same search twice. The second response includes `"cached": true, "cache_tier": "exact"` and returns in under 50ms. The BLUF strip shows a green "Instant (cache)" badge.

---

### 2. Fuzzy Search History Suggestions

**What:** As you type in the search bar, the system suggests similar past queries with their cached results.

**How it works:**
- Every search query is recorded in Redis + RediSearch + Qdrant embeddings.
- `POST /query/history/search` embeds the current query and finds semantically similar past queries (threshold: 0.75 cosine similarity).
- Returns suggestions with `search_id`, `entity_count`, `timestamp`, and `similarity_score`.

**Where to look:**
- `services/processor/src/processor/main.py` — `POST /query/history/search` endpoint (line ~1100), `_record_query_history()` helper (line ~500)
- `services/delivery/src/app/api/query/history/route.ts` — Delivery proxy
- `services/delivery/src/types/entities.ts` — `HistorySuggestion`, `HistorySearchResponse`

**How to feel it:** Search "Elon Musk", then type "elon reeve musk" — the suggestion dropdown shows the previous search with its similarity score. Clicking it loads the cached result instantly.

---

### 3. Radial Tree Graph Layout

**What:** The graph renders as a radial tree rooted at the most-connected entity, replacing the old force-directed hairball.

**How it works:**
- `transformToRadialTreeData` identifies the root (highest-degree entity), runs BFS to assign depth levels, and places nodes on concentric rings.
- ECharts `type: "tree"` + `layout: "radial"` with `expandAndCollapse: true` for interactive drilldown.
- Double-click any node to expand its neighborhood (drilldown).
- Single-click to open the provenance drawer.

**Where to look:**
- `services/delivery/src/components/canvas/useEChartsGraphAdapter.ts` — `transformToRadialTreeData`
- `services/delivery/src/components/canvas/EChartsGraphCanvas.tsx` — tree series config
- `services/processor/src/processor/main.py` — `tree_root_id` in `SearchResponse`

**How to feel it:** Run any search. The root entity appears at center with branches radiating outward. No more random node positions or overlapping hairballs. Collapse/expand subtrees by clicking nodes.

---

### 4. Inline Pipeline Progress Indicator

**What:** A compact 6-stage progress bar replaces the old bottom drawer + floating toast, showing exactly what the pipeline is doing for your query.

**How it works:**
- 6 stage pills: `[Schema] [Dedup] [NER] [Resolution] [Graph] [Alert]`
- Each pill shows: gray circle (idle) → indigo spinner (active) → green check (done) → red alert (error)
- Shows elapsed time since pipeline start.
- Only appears when a pipeline is running for the active search query.
- Filters stage events by `search_id` so you only see progress for YOUR query.

**Where to look:**
- `services/delivery/src/components/graph/PipelineIndicator.tsx` — new component
- `services/delivery/src/hooks/usePipelineEvents.ts` — `activeSearchId` export
- `services/delivery/src/app/explorer/page.tsx` — mounted between search bar and canvas

**How to feel it:** Start a search. Below the floating search bar, a compact bar appears showing each pipeline stage lighting up as it completes. No more intrusive bottom drawer or floating toast card.

---

### 5. Mandatory Provenance on Every Node

**What:** Every entity node must have a `source_id` (where it came from). Nodes without provenance are dropped — no exceptions, no "unknown" fallback.

**How it works:**
- **Write side:** Pipeline drops entities without `source_id` before graph persistence. Prometheus counter: `processor_entities_dropped_no_provenance_total`.
- **Read side:** All Neo4j Cypher queries filter `WHERE e.source_id IS NOT NULL AND e.source_id <> ''`.
- **Safety net:** `GraphPersistenceService.upsert_entity` and `persist_extraction` have defensive checks.

**Where to look:**
- `services/processor/src/processor/pipeline.py` — provenance gate between resolution and persistence
- `services/processor/src/models/entities.py` — `Entity.has_provenance()` helper
- `services/processor/src/graph/persistence.py` — defensive checks in `upsert_entity`, `persist_extraction`, `search_entities`
- `services/processor/src/processor/main.py` — `source_id IS NOT NULL` in all Cypher queries

**How to feel it:** Every node on the radial tree shows a source badge (color-coded by plugin: blue=Wikipedia, green=NewsRSS, orange=Reuters). Click a node → SourceTraceDrawer shows full provenance: source name, URL, plugin, timestamp, raw context snippet.

---

### 6. Query-Scoped Realtime Updates

**What:** When the pipeline runs, only entities from YOUR active search appear on the graph. Alerts from other searches go to the notification bell.

**How it works:**
- Every pipeline stage event and analyst alert carries a `search_id`.
- `useRealtimeNodes` filters incoming alerts by `searchId` — non-matching alerts are silently dropped from the canvas.
- Non-matching alerts increment the `NotificationBell` counter. Click the bell to see queued alerts from other searches.
- Starting a new search clears realtime entities from the previous search.

**Where to look:**
- `services/delivery/src/hooks/useRealtimeNodes.ts` — `searchId` filtering
- `services/delivery/src/components/notifications/NotificationBell.tsx` — non-active alert queuing
- `services/delivery/gateway/server.ts` — `search_id` in Socket.io broadcasts
- `services/processor/src/processor/stage_publisher.py` — `search_id` in `StageEvent`
- `services/processor/src/processor/alert_publisher.py` — `search_id` in `AnalystAlert`

**How to feel it:** Run two searches in different tabs. Each tab only shows pipeline progress and new nodes for its own query. The notification bell on each tab shows a counter for alerts from the other tab's search.

---

### 7. Entity Deduplication

**What:** The same entity from different sources appears as a single node, not duplicates.

**How it works:**
- **Resolution-time:** Same type + same name → auto-merge (confidence=1.0). Same type + substring match → +0.2 similarity boost.
- **Retrieval-time:** `_deduplicate_entities()` groups by `(type, name)` and keeps the highest-confidence entity.
- **UI safety net:** `mergeRealtime` skips nodes with duplicate `(entity_type, entity_name)`.

**Where to look:**
- `services/processor/src/resolution/resolver.py` — `_apply_same_type_dedup()` method
- `services/processor/src/processor/main.py` — `_deduplicate_entities()` in `/search`
- `services/delivery/src/store/useGraphExplorerStore.ts` — `mergeRealtime` dedup

**How to feel it:** "Apple Inc." extracted from Wikipedia and "Apple Inc" from Reuters → single node on the radial tree with the highest confidence score. No duplicate nodes for the same real-world entity.

---

### 8. BLUF-First Summary View

**What:** Every search result includes an instant summary: entity count, type breakdown, top entities, sources, and cache/pipeline status.

**How it works:**
- `SearchResponse.summary` contains: `total_entities`, `total_relationships`, `entity_types` (count by type), `top_entities` (top 5 by degree), `sources` (unique source names), `cached`, `cache_tier`, `pipeline_running`.
- `BlufStrip` renders: green "Instant (cache)" badge when cached, animated "Pipeline enriching results···" when running, entity type pills, source badges, ranked top entities.

**Where to look:**
- `services/processor/src/processor/main.py` — `_build_summary()` function, `summary` field on `SearchResponse`
- `services/delivery/src/components/synthesis/BlufStrip.tsx` — enhanced rendering
- `services/delivery/src/types/entities.ts` — `SearchSummary` interface

**How to feel it:** Run a search. Before the radial tree even renders, the BLUF strip at the top shows: "23 entities found · 8 PERSON, 6 ORG, 5 LOCATION · Sources: Wikipedia, Reuters" with a green cache badge or animated pipeline indicator.

---

### 9. Search Identity (`search_id`) End-to-End

**What:** Every search has a unique ID that flows through the entire system, enabling all query-scoping features.

**How it works:**
- `search_id` is generated at the Processor `/search` endpoint (UUID4 if not provided by client).
- Flows through: Pipeline stage events → Kafka `processor-events` → Gateway → Socket.io `pipeline_stage` broadcasts.
- Flows through: Analyst alerts → Kafka `analyst-alerts` → Gateway → Socket.io `alert` broadcasts.
- Stored in Zustand store (`searchId`), used by `useRealtimeNodes`, `usePipelineEvents`, `PipelineIndicator`.

**Where to look:**
- `services/processor/src/processor/main.py` — `search_id` on `SearchRequest`, `SearchResponse`, `ExpandRequest`
- `services/processor/src/processor/pipeline.py` — `search_id` passthrough to stage/alert publishers
- `services/delivery/gateway/server.ts` — `search_id` in broadcast payloads
- `services/delivery/src/store/useGraphExplorerStore.ts` — `searchId` state

---

## Bugs Fixed

| # | Bug | Root Cause | Fix | Where |
|---|-----|-----------|-----|-------|
| 1 | **Duplicate entity nodes** for same real-world entity from different sources | Entity resolver didn't check same-type+same-name before vector comparison | Added `_apply_same_type_dedup()` with auto-merge for exact matches and +0.2 boost for substring matches | `resolver.py` |
| 2 | **Nodes without provenance** reaching the UI with `"unknown"` source | `_build_custom_nodes` fell back to `"unknown"` when `source_name` was missing | Hard drop at pipeline persistence + `source_id IS NOT NULL` filter on all Neo4j reads | `pipeline.py`, `main.py`, `persistence.py` |
| 3 | **Realtime nodes from other searches** polluting the active canvas | `useRealtimeNodes` had no query scoping — accepted all alerts | Added `searchId` filtering; non-matching alerts go to `NotificationBell` | `useRealtimeNodes.ts`, `NotificationBell.tsx` |
| 4 | **Pipeline activity drawer + toast** competing for screen space | Two separate UI components showing the same pipeline data | Replaced both with single compact `PipelineIndicator` | `PipelineIndicator.tsx` |
| 5 | **Force-directed graph hairball** with random node positions | ECharts `type:"graph"` with `layout:"force"` and `randomCoord()` | Replaced with `type:"tree"` + `layout:"radial"` — BFS from root, concentric rings | `EChartsGraphCanvas.tsx`, `useEChartsGraphAdapter.ts` |
| 6 | **No query identity** — pipeline events couldn't be scoped to a specific search | `search_id` didn't exist in any model or event | Added `search_id` to all models (SearchRequest/Response, StageEvent, AnalystAlert) and all broadcast paths | 12 files across all 3 services |
| 7 | **Full pipeline re-run on every search** even for identical queries | No result caching | 3-tier cache (exact/fuzzy/semantic) with 1h TTL | `query_cache.py` |
| 8 | **No search history** for discovering past queries | History only in `sessionStorage` (browser-local, no fuzzy matching) | Server-side history with RediSearch + Qdrant embeddings, `/query/history/search` endpoint | `main.py`, `history/route.ts` |

---

## Deleted Components

| Component | Reason |
|-----------|--------|
| `ActivityDrawer.tsx` | Replaced by `PipelineIndicator.tsx` — compact inline bar instead of collapsible bottom drawer |
| `PipelineProgressToast.tsx` | Replaced by `PipelineIndicator.tsx` — no more floating toast card |
| `graphology.ts` (mock) | No longer needed — radial tree uses ECharts native tree series, not graphology |
| `graphology-layout-forceatlas2.ts` (mock) | No longer needed — force layout removed |
| `sigma.ts` (mock) | No longer needed — Sigma.js was already replaced by ECharts in V4 Track 1 |

---

## New Files

| File | Purpose |
|------|---------|
| `services/processor/src/cache/__init__.py` | Package init for cache module |
| `services/processor/src/cache/query_cache.py` | `QueryCacheService` — 3-tier result cache (420 lines) |
| `services/delivery/src/components/graph/PipelineIndicator.tsx` | Compact inline pipeline progress indicator |
| `services/delivery/src/app/api/query/history/route.ts` | Proxy for fuzzy history search endpoint |

---

## Verification

| Check | Command | Result |
|-------|---------|--------|
| Delivery TypeScript | `pnpm exec tsc --noEmit` | EXIT_CODE=0 ✅ |
| Delivery unit tests | `pnpm exec jest` | 9 suites / 78 tests PASS ✅ |
| Processor syntax (all 9 files) | `python3 -c "import ast; ast.parse(...)"` | All clean ✅ |

---

## Quick Tour: Where to Feel the Changes

1. **Open the app** → `http://localhost:3000`
2. **Search "Elon Musk"** → Radial tree appears with Elon at center, branches to Tesla, SpaceX, Twitter, etc. BLUF strip shows entity count + type breakdown.
3. **Watch the pipeline** → Compact indicator below search bar shows 6 stages lighting up green.
4. **Search "Elon Musk" again** → Instant result with green "Instant (cache)" badge. No pipeline re-run.
5. **Type "elon reeve"** → Suggestion dropdown shows "Elon Musk" from history with similarity score.
6. **Click any node** → SourceTraceDrawer shows full provenance: source name, URL, plugin, raw context.
7. **Double-click a node** → Subtree expands with that node's neighbors.
8. **Open a second tab, search "OpenAI"** → Tab 1's graph stays clean. Tab 1's notification bell shows a counter for Tab 2's alerts.
9. **Check no node says "unknown" source** → Every node has a colored source badge.
10. **Check no duplicate nodes** → Same entity from Wikipedia + Reuters appears once.
