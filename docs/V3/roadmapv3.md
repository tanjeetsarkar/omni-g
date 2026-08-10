# Omni-G Enhancement Plan: Delivery UX + Challenge Remediation + OpenRouter Integration

Based on my analysis of the codebase, the architecture analysis document, and the gap matrix, here is a comprehensive plan organized into three workstreams.

---

## Workstream A: OpenRouter API Integration (Offload LLM from Local System)

### Problem
Currently, the system relies on a local Ollama daemon for:
1. **Briefing script generation** (`BriefingScriptGenerator._call_ollama()`) — calls `OLLAMA_URL/api/generate` with `qwen2.5:3b`
2. **Entity resolver embeddings** (`EntityResolver._embed()`) — calls `OLLAMA_URL/api/embeddings` with `nomic-embed-text`

The Ollama container is commented out in `docker-compose.yml`, and the gap matrix notes: *"host Ollama daemon still bound to 127.0.0.1:11434, so container-to-host LLM calls fail."* This puts unnecessary load on your local system.

### Solution: OpenRouter as the LLM Backend

OpenRouter provides an OpenAI-compatible API at `https://openrouter.ai/api/v1/chat/completions`. Since the codebase already uses `httpx` and `AsyncOpenAI` clients, integration is straightforward.

**A1. Add OpenRouter config to `services/processor/src/processor/config.py`:**
```python
# LLM Provider (OpenRouter or Ollama)
llm_provider: str = Field(default="ollama", alias="LLM_PROVIDER")  # "openrouter" | "ollama"
openrouter_api_key: str | None = Field(default=None, alias="OPENROUTER_API_KEY")
openrouter_base_url: str = Field(default="https://openrouter.ai/api/v1/chat/completions", alias="OPENROUTER_BASE_URL")
openrouter_model: str = Field(default="meta-llama/llama-3.1-8b-instruct", alias="OPENROUTER_MODEL")
openrouter_embedding_model: str = Field(default="text-embedding-3-small", alias="OPENROUTER_EMBEDDING_MODEL")
```

**A2. Create a unified LLM client abstraction** — `services/processor/src/llm/client.py`:
- A `LLMClient` class that wraps either OpenRouter or Ollama based on `LLM_PROVIDER` env var
- For OpenRouter: uses `AsyncOpenAI(base_url=openrouter_base_url, api_key=openrouter_api_key)` — OpenRouter is fully OpenAI-compatible
- For Ollama: keeps existing `httpx` calls to `OLLAMA_URL`
- Provides `generate(prompt, **kwargs) -> str` and `embed(text) -> list[float]` methods
- This becomes the single entry point for all LLM calls in the Processor

**A3. Refactor `BriefingScriptGenerator` to use the unified client:**
- Replace direct `httpx` calls to Ollama with `LLMClient.generate()`
- When `LLM_PROVIDER=openrouter`, briefing generation calls OpenRouter's chat completions endpoint
- Fallback to placeholder script on any failure (existing behavior preserved)

**A4. Refactor `EntityResolver._embed()` to use the unified client:**
- Replace direct Ollama HTTP calls with `LLMClient.embed()`
- When `LLM_PROVIDER=openrouter`, uses OpenRouter's embeddings endpoint
- Hash-based fallback preserved for when API is unreachable
- **Bonus:** This also addresses Challenge 4.4 (entity resolver embedding inconsistency) — we can optionally route embeddings through BGE-M3 locally or OpenRouter remotely

**A5. Update `docker-compose.yml`:**
- Add `LLM_PROVIDER`, `OPENROUTER_API_KEY`, `OPENROUTER_MODEL` env vars to `processor` and `processor-worker` services
- Keep Ollama commented out (no longer needed when using OpenRouter)
- Remove `host.docker.internal` LLM routing since OpenRouter is cloud-hosted

---

## Workstream B: Delivery UX Enhancements (Section 5 of the Analysis)

### B1. BLUF / Synthesis Strip Above the Canvas
**What:** Add a collapsible summary panel above the graph canvas that surfaces the "so what" from the calibrated context units.

**Implementation:**
- New component: `services/delivery/src/components/synthesis/BlufStrip.tsx`
- Consumes the `context_units` array already returned by `POST /api/query` (currently fetched but only shown per-node in `SourceTracePane`)
- Two modes:
  - **Extractive (zero-LLM):** Show top-3 context units by score as bullet points with entity highlights — uses data already computed by `EvidenceCalibrator`
  - **LLM-synthesized (optional):** New Processor endpoint `POST /synthesize` that takes the calibrated context array and calls OpenRouter for a 2-3 sentence BLUF summary
- Integrate into `explorer/page.tsx` above the `EChartsGraphCanvas`
- Collapsible (analyst can minimize to focus on graph)

**New Processor endpoint** — `POST /synthesize` in `main.py`:
```python
@app.post("/synthesize", tags=["synthesis"])
async def synthesize(body: SynthesisRequest) -> JSONResponse:
    # Takes context_units + query → LLMClient.generate() → BLUF summary
    # Falls back to extractive summary if LLM unavailable
```

### B2. Legend-as-Filter with Category Counts
**What:** Extend `EChartsGraphCanvas` legend to show counts per entity type and allow toggle-to-filter.

**Implementation in `EChartsGraphCanvas.tsx`:**
- Build `seriesCategories` with count badges: `{name: cat, count: nodes.filter(n => n.category === cat).length}`
- Wire ECharts `legend.selected` state to React state for persistence
- Add `legend.selectedMode: 'multiple'` to enable click-to-toggle
- Show counts in legend text: `formatter: (name) => \`${name} (${countMap[name]})\``

### B3. Confidence-Driven Visual Encoding
**What:** Map entity confidence to visual properties beyond just `symbolSize`.

**Implementation in `useEChartsGraphAdapter.ts`:**
- Add `itemStyle.opacity` based on confidence: `opacity = 0.4 + (confidence * 0.6)` — low-confidence entities visually recede
- Add `itemStyle.borderColor` and `borderWidth` for high-confidence entities (>0.8): thicker border
- Add `label.show` conditional: only show labels for nodes with confidence > 0.3 to reduce clutter
- Update tooltip to show confidence as a visual bar, not just a number

### B4. Search History & Saved Views
**What:** Persist recent searches and allow re-running them.

**Implementation:**
- New hook: `services/delivery/src/hooks/useSearchHistory.ts`
  - Uses `sessionStorage` (safe in Next.js client components)
  - Stores last 10 searches as `{query, timestamp, entityCount}` objects
  - Provides `addSearch()`, `clearHistory()`, `getHistory()`
- Update empty state in `explorer/page.tsx`:
  - Replace static "Try: Sundar Pichai..." text with clickable recent-search chips
  - Each chip calls `runSearch(query)` on click
- Add "Save this view" button in header that stores current query + graph state to `sessionStorage`

### B5. Layout Switcher (Force / Circular / Grid)
**What:** Expose ECharts' native layout options as a toggle.

**Implementation in `EChartsGraphCanvas.tsx`:**
- Add `layoutType` prop: `"force" | "circular" | "none"`
- Add a 3-button toggle component above the canvas (or floating top-right)
- Map to ECharts `series.layout` config:
  - `force`: existing config (repulsion, gravity, edgeLength)
  - `circular`: `layout: 'circular'` with `circular.rotateLabel: true`
  - `none`: `layout: 'none'` (positions from data, useful with pre-computed layouts)
- Persist selection in `sessionStorage`

### B6. Reconnect BriefingPanel to Graph Flow
**What:** Make briefing entity mentions clickable to navigate to the graph.

**Implementation:**
- New Processor endpoint: `GET /briefings/{id}/transcript` — returns the briefing script text + extracted entity names
- Update `BriefingPanel.tsx`:
  - When playing a briefing, also fetch the transcript
  - Parse entity names from the transcript (simple regex or NER on client side)
  - Render entity names as clickable chips below the audio player
  - Clicking a chip calls `router.push('/explorer?q=' + entityName)`
- Move `BriefingPanel` from a disconnected side panel into the explorer page as a collapsible bottom drawer or right-side tab

### B7. Persistent Error/Notification Log
**What:** Keep dismissed errors accessible via a bell icon in the header.

**Implementation:**
- New component: `services/delivery/src/components/notifications/NotificationBell.tsx`
- New hook: `services/delivery/src/hooks/useNotificationLog.ts`
  - React Context provider at the explorer page level
  - Ring buffer (max 50 entries) of `{id, type, message, timestamp, dismissed}`
  - `pushNotification()`, `dismissAll()`, `getUnreadCount()`
- Update `PipelineProgressToast` dismiss handler to push into the notification log
- Add bell icon to header with unread count badge
- Dropdown shows recent errors/warnings with timestamps

### B8. Improved Empty State with Trending/Recent Entities
**What:** Replace the static empty state with dynamic suggestions.

**Implementation:**
- New Processor endpoint: `GET /trending?tenant_id=X&limit=5` — returns recently-added high-confidence entities
- Update empty state in `explorer/page.tsx`:
  - Show "Recently added" section with entity name chips
  - Show "Try these queries" with example queries based on actual entity types in the graph
  - Loading skeleton while trending data loads

---

## Workstream C: Challenge Remediation (Section 4 of the Analysis)

### C1. PPR Result Caching (Challenge 4.1)
**What:** Cache APOC PPR results in Redis with short TTL.

**Implementation in `services/processor/src/retrieval/relational.py`:**
- Before calling `_ppr_retrieve`, check Redis for cached results keyed on `ppr:{tenant_id}:{hash(sorted(anchor_ids))}:{d_max}`
- If cached, return immediately (TTL: 60 seconds — short enough for freshness, long enough to absorb repeated queries)
- If not cached, run PPR, store results in Redis, then return
- Add `PPR_CACHE_HITS` and `PPR_CACHE_MISSES` Prometheus counters

### C2. Async NER Extraction (Challenge 4.2)
**What:** Offload blocking spaCy/GLiNER calls to a thread pool.

**Implementation in `services/processor/src/processor/pipeline.py`:**
- Wrap `self._zeromem_extractor.extract()` in `asyncio.get_event_loop().run_in_executor(process_pool, ...)`
- Create a module-level `ProcessPoolExecutor` with configurable max workers
- Alternatively (and better for production): ensure `CELERY_ENABLED=true` so NER runs in Celery worker processes, not the asyncio event loop
- Add `NER_EXTRACTION_LATENCY` Prometheus histogram (already exists as `PIPELINE_STAGE_DURATION.labels(stage="ner_extraction")`)

### C3. Fail-Open Metrics (Challenge 4.3)
**What:** Add distinct Prometheus counters for each fail-open branch.

**Implementation across `pipeline.py`:**
- `GLINER_FAILURES_TOTAL = Counter("processor_gliner_failures_total", ...)`
- `TEMPORAL_INSERT_FAILURES_TOTAL = Counter("processor_temporal_insert_failures_total", ...)`
- `VECTOR_INDEX_FAILURES_TOTAL = Counter("processor_vector_index_failures_total", ...)`
- `CONTEXT_UNIT_PERSIST_FAILURES_TOTAL = Counter("processor_context_unit_persist_failures_total", ...)`
- Increment in each `except` block alongside existing `logger.exception()`

### C4. Shared Temporal Hash Module (Challenge 4.5)
**What:** Extract the episode-hash function into one shared module.

**Implementation:**
- New module: `services/processor/src/graph/temporal_hashes.py`
- Move `_assign_temporal_ids()` and `_h()` from `pipeline.py` into this module
- Import in both `pipeline.py` and `retrieval/temporal.py`
- Add logging (not silent substitution) when temporal cue parsing fails in `temporal.py`

### C5. Outbox Pattern for Polyglot Persistence (Challenge 4.6)
**What:** Reconcile Neo4j/Qdrant/Postgres writes via per-sink consumers.

**Implementation (phased approach):**
- **Phase 1 (immediate):** Add a retry queue for failed writes. When any store fails, publish a `reconciliation` event to a new Kafka topic `processor-reconciliation`
- **Phase 2 (follow-on):** Create per-sink consumers that read from `processor-reconciliation` and retry with exponential backoff
- This is a larger architectural change — I recommend deferring to a separate task unless you want it included now

---

## Implementation Order (Recommended)

| Priority | Task | Effort | Impact |
|----------|------|--------|--------|
| **P0** | A1-A5: OpenRouter integration | Medium | High — removes local system load |
| **P1** | B1: BLUF/Synthesis strip | Medium | High — highest-leverage UX improvement |
| **P2** | B2: Legend-as-filter | Low | Medium — quick win |
| **P3** | B3: Confidence visual encoding | Low | Medium — quick win |
| **P4** | B4: Search history | Low | Medium — quick win |
| **P5** | B5: Layout switcher | Low | Medium — quick win |
| **P6** | C1: PPR caching | Low | Medium — performance |
| **P7** | C3: Fail-open metrics | Low | Medium — observability |
| **P8** | C4: Shared temporal hash | Low | Low — correctness |
| **P9** | C2: Async NER | Low | Medium — performance |
| **P10** | B7: Persistent error log | Medium | Low — UX polish |
| **P11** | B6: Briefing reconnection | Medium | Medium — UX integration |
| **P12** | B8: Trending empty state | Medium | Low — UX polish |
| **P13** | C5: Outbox pattern | High | Medium — reliability (defer) |

---

## Files Affected

**New files:**
- `services/processor/src/llm/client.py` — unified LLM client
- `services/processor/src/graph/temporal_hashes.py` — shared hash module
- `services/delivery/src/components/synthesis/BlufStrip.tsx` — BLUF summary panel
- `services/delivery/src/components/notifications/NotificationBell.tsx` — error log
- `services/delivery/src/hooks/useSearchHistory.ts` — search persistence
- `services/delivery/src/hooks/useNotificationLog.ts` — notification context

**Modified files:**
- `services/processor/src/processor/config.py` — OpenRouter settings
- `services/processor/src/processor/main.py` — new `/synthesize` and `/trending` endpoints
- `services/processor/src/briefing/script_generator.py` — use unified LLM client
- `services/processor/src/resolution/resolver.py` — use unified LLM client for embeddings
- `services/processor/src/processor/pipeline.py` — async NER, fail-open metrics, shared hashes
- `services/processor/src/retrieval/relational.py` — PPR caching
- `services/processor/src/retrieval/temporal.py` — shared hashes, logging
- `services/delivery/src/app/explorer/page.tsx` — integrate all new UX components
- `services/delivery/src/components/canvas/EChartsGraphCanvas.tsx` — legend-as-filter, layout switcher
- `services/delivery/src/components/canvas/useEChartsGraphAdapter.ts` — confidence encoding
- `services/delivery/src/components/briefing/BriefingPanel.tsx` — graph reconnection
- `services/delivery/src/components/graph/PipelineProgressToast.tsx` — notification log integration
- `infrastructure/docker-compose.yml` — OpenRouter env vars
- `docs/agent-contexts/gap-matrix.md` — update after implementation

---

## Risks & Mitigations

1. **OpenRouter API costs:** Mitigated by using smaller models (`llama-3.1-8b-instruct`) and only calling LLM for briefing synthesis (not ingestion — Zero-Mem NER stays local)
2. **OpenRouter latency:** Briefing generation is not latency-sensitive (runs via Celery Beat). Entity resolution embeddings are the concern — mitigate with Redis caching of embeddings
3. **Breaking existing tests:** The `BriefingScriptGenerator` and `EntityResolver` tests will need updates to mock the new `LLMClient` instead of direct HTTP calls
4. **BLUF strip data availability:** The `context_units` array is already returned by `/search` — no backend changes needed for the extractive mode. LLM-synthesized mode requires the new `/synthesize` endpoint

---

Does this plan match what you're looking for? If you'd like to adjust scope (e.g., defer the outbox pattern, or prioritize certain UX improvements), let me know. Once you're satisfied, **toggle to Act mode** and I'll begin implementation starting with the OpenRouter integration (P0).
