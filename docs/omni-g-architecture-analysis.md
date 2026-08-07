# Omni-G: Data Flow, Information Architecture, Zero-Mem Processor & Delivery Review

*A structural analysis of the current codebase (V3 Zero-Mem branch), grounded in the actual source files in the repository.*

---

## 1. End-to-End Data Flow

Omni-G is a three-service pipeline — **Aggregator (Go) → Kafka → Processor (Python) → Kafka → Delivery (Next.js + Gateway)** — with Neo4j, Qdrant, Redis, and Postgres as the persistence/retrieval substrate.

### 1.1 Ingestion path

```
Analyst types query
      │
      ▼
POST /api/search (Delivery Next.js route) ──► POST /search (Aggregator :8080)
                                                     │
                                    SearchHandler fans out goroutines,
                                    one per configured MCP plugin
                                                     │
                                    MCP Client (JSON-RPC 2.0 + SSE) ──► mcp-wikipedia / mcp-wikidata /
                                                                          mcp-newsrss / mcp-reuters / mcp-echo
                                                     │
                                    Each returned ContentBlock.Text is JSON-
                                    decoded into a payload and pushed into
                                    Pipeline.ProcessBlock()
                                                     │
                                    Pipeline.Process() calls the Processor's
                                    POST /validate sidecar
                                                     │
                              valid=true ──► kafka.Producer.Publish(RawEvent) → topic "raw-feed"
                              valid=false ─► dropped, counted in Prometheus (no error to caller)
```

The `RawEvent` envelope produced onto Kafka is defined in `services/aggregator/internal/kafka/producer.go`:

```go
type RawEvent struct {
	ID              string         `json:"id"`
	Source          string         `json:"source"`
	Timestamp       time.Time      `json:"timestamp"`
	Payload         map[string]any `json:"payload"`
	PluginVersion   string         `json:"plugin_version,omitempty"`
	PluginName      string         `json:"plugin_name,omitempty"`
	IngestLatencyMs int64          `json:"ingest_latency_ms"`
	SchemaVersion   string         `json:"schema_version"`
	TenantID        string         `json:"tenant_id,omitempty"`
	KIQID           string         `json:"kiq_id,omitempty"`
}
```

Validation is delegated to the Processor's `/validate` endpoint rather than embedded in the Aggregator — a deliberate decoupling documented in `docs/Architecture.md` §11.1 ("Ingress validation is tightly coupled to Processor availability").

### 1.2 Processing path (Kafka consumer → Celery → Pipeline)

```
Kafka "raw-feed"
      │
RawEventConsumer.process_messages()  (services/processor/src/kafka/consumer.py)
      │  poll(timeout_ms=200) loop, manual offset commit, DLQ on handler exception
      ▼
if CELERY_ENABLED:  enqueue_process_event(event) → Celery task "processor.process_event"
else:                runtime.process_event(event)  (inline, same worker)
      │
      ▼
ProcessingPipeline.process(event)   (services/processor/src/processor/pipeline.py)
      │
      ├─ Step 1: RawEventEnvelope.model_validate()      → SchemaViolationError → DLQ
      ├─ Step 2: ContentDeduplicator.check_and_set()     → SHA-256 + Redis Lua, drop dup
      ├─ Step 3: ZeroMemExtractor.extract()               → spaCy + GLiNER, ZERO LLM calls
      │      ├─ persist ContextUnit + CO_OCCURRED_IN edges (Neo4j)
      │      ├─ link_adjacent_contexts (NEXT_CONTEXT edge)
      │      ├─ ContextUnitIndexer.upsert_to_qdrant()      (BGE-M3 dense vector)
      │      └─ TemporalStore.insert_context_unit_temporal() (Postgres)
      ├─ Step 4: EntityResolver.resolve_and_persist()      → Qdrant blocking + Neo4j structural match
      ├─ Step 5: GraphPersistenceService.persist_extraction() → atomic Neo4j transaction
      └─ Step 6: AlertPublisher.publish()  (if confidence > 0.5) → Kafka "analyst-alerts"
      │
      └─ StageEventPublisher.publish() before/after every step → Kafka "processor-events"
```

Both Kafka side-channel topics (`analyst-alerts`, `processor-events`) are consumed by the Delivery **Gateway** (a standalone Node process, `services/delivery/gateway/server.ts`) and rebroadcast to browsers over Socket.io, scoped to `tenant:{tenant_id}` rooms.

### 1.3 Retrieval path (search / drill-down)

```
Delivery UI search box
      │
      ▼
POST /api/query (Next.js) ──► POST /search (Processor :8001)
      │
      ├─ QueryProfiler.profile(query)         → spaCy NER → route: "relational" | "local", d_max
      ├─ RelationalRetriever.retrieve()        → Qdrant entity alignment → APOC PPR (γ=0.6) → BFS fallback
      ├─ TemporalRetriever.retrieve()          → Postgres episode/window hierarchy → Neo4j recency fallback
      │        (both run concurrently via asyncio.gather)
      ├─ DualViewFusion.fuse()                 → per-view normalize → ρ-weighted blend (route-biased)
      ├─ EvidenceCalibrator.calibrate()        → dedup by 100-char fingerprint, token-budget cutoff
      └─ Neo4j fetch of Entity nodes for the calibrated ContextUnit.entity_ids
      │
      ▼
{ entities, relationships, context_units } → Delivery ECharts canvas (force-directed graph)
```

Drill-down (double-click a node) reuses the same APOC-PPR machinery through `POST /query/expand`, scoped to a single anchor node — this is the "zero-LLM incremental expansion" tested end-to-end in `tests/e2e/test_echarts_drilldown_pipeline.py` with a hard <120 ms latency assertion.

### 1.4 Real-time delivery path

```
Kafka "analyst-alerts" / "processor-events"
      │
Gateway (Node.js/KafkaJS) consumer group "delivery-gateway"
      │
      ├─ handleKafkaMessageValue()   → validate alert schema → io.to(`tenant:{id}`).emit("alert", …)
      └─ handleStageEventValue()    → io.to(`tenant:{id}`).emit("pipeline_stage", …)
      │
      ▼
Browser Socket.io client (src/lib/socket.ts) — single shared singleton
      │
      ├─ usePipelineEvents()  → drives PipelineProgressToast / ActivityDrawer stage checklist
      └─ useRealtimeNodes()   → on "alert", POST /api/entities (direct Neo4j fetch, NOT a new search)
                                  → merges new nodes into the ECharts canvas
```

---

## 2. Information Architecture

### 2.1 Service boundaries and ownership

| Service | Owns | Does not own |
|---|---|---|
| **Aggregator** (Go) | MCP discovery/polling, schema validation call-out, Kafka production, `/search` & `/enrich` fan-out | entity resolution, graph writes, dissemination |
| **Processor** (Python/FastAPI) | Kafka intake + DLQ, Celery dispatch, ZeroMem extraction, entity resolution, graph persistence, dual-view retrieval, alerting, briefings | plugin orchestration, UI rendering |
| **Delivery** (Next.js + Node gateway) | Search UI, ECharts graph, real-time Socket.io bridge, briefing playback | raw ingestion, long-running analysis, direct graph writes (though `NEO4J_URL` creds are still present client-side — see §4) |

### 2.2 Domain model layers

Two model families coexist in the graph, per `docs/V2/DOMAIN-MODEL.md` and the actual V3 code:

1. **Generic knowledge layer** (`services/processor/src/models/entities.py`)
   - `Entity` — open-ended `type: str`, `properties: dict`, `confidence`, `source_spans: list[EvidenceSpan]`
   - `Relationship` — open-ended UPPER_SNAKE_CASE `type`
   - `ContextUnit` — the **primary V3 node**: raw text chunk + temporal hierarchy IDs (`session_id`, `episode_id`, `window_id`, `turn_id`)
   - `ExtractionResult` — container with `entity_context_weights: dict[str, float]` (the Zero-Mem co-occurrence weights)

2. **V2 intelligence-cycle layer** (KIQ / CollectedEvidence / Hypothesis / Assessment / CollectionGap) — defined in `docs/V2/DOMAIN-MODEL.md` but **explicitly deprecated and removed** in the V3 migration (`docs/V3/V3-implementation-plan.md` Phase 2, confirmed in `docs/agent-contexts/gap-matrix.md`: *"KIQ, CollectedEvidence, Hypothesis, Assessment, CollectionGap models... Replaced by ContextUnit-first paradigm"*).

### 2.3 Neo4j schema (current, V3)

```cypher
// Node labels
(:Entity:{TypeLabel}:{tenant_label} {id, type, name, confidence, tenant_id, properties, source_id, aliases, created, modified})
(:ContextUnit {id, text, source_id, tenant_id, session_id, episode_id, window_id, created, metadata})

// Edges
(:Entity)-[:CO_OCCURRED_IN {weight, tenant_id}]->(:ContextUnit)
(:ContextUnit)-[:NEXT_CONTEXT {tenant_id}]->(:ContextUnit)
(:Entity)-[:SAME_AS {confidence, tenant_id}]->(:Entity)              // ambiguous merges
(:Entity)-[:{ANY_RELATIONSHIP_TYPE} {id, confidence, tenant_id}]->(:Entity)
```

`GraphSchemaManager.initialize()` (`services/processor/src/graph/schema.py`) creates 12 constraints/indexes in one pass — 8 for `:Entity`, 4 for `:ContextUnit` — all idempotent (`IF NOT EXISTS`).

### 2.4 Kafka topic map

| Topic | Producer | Consumer | Payload |
|---|---|---|---|
| `raw-feed` | Aggregator | Processor | `RawEvent` envelope |
| `raw-feed.dlq` | Processor consumer | (manual inspection) | `{original_message, error, error_type, partition, offset}` |
| `analyst-alerts` | Processor `AlertPublisher` | Delivery Gateway | `AnalystAlert` |
| `processor-events` | Processor `StageEventPublisher` | Delivery Gateway | `StageEvent` (8-stage pipeline progress) |

### 2.5 Storage substrate roles

| Store | Role in V3 |
|---|---|
| **Redis** | SHA-256 dedup keys (Lua atomic check-and-set), Celery broker/result backend (separate logical DBs) |
| **Neo4j + APOC** | Entity-Context graph, Personalized PageRank for relational retrieval |
| **Qdrant** | Two collections per tenant: `entities_{tenant_id}` (resolution blocking) and `context_units_{tenant_id}` (BGE-M3 dense retrieval) |
| **Postgres** | Temporal hierarchy (`context_units_temporal`, `temporal_episodes`) — added specifically for V3 |
| **MinIO** | Audio briefing objects |

---

## 3. Deep Dive: How Zero-Mem Is Implemented in the Processor

The target paper (Zero-Mem, arXiv 2607.29377) proposes a **non-generative** memory/retrieval paradigm: entity-context graphs built by classical NER instead of LLMs, multi-hop relational retrieval via Personalized PageRank, a parallel temporal-hierarchy route, and LLM usage reserved strictly for final synthesis. The codebase's `docs/V3/proposed-architecture.md` and `docs/V3/V3-implementation-plan.md` map directly onto this, and the implementation is real (not just planning docs) — it's exercised in `test_pipeline.py`, `test_echarts_drilldown_pipeline.py`, and `test_graph.py`.

### 3.1 Extraction — replacing the LLM with NER

`services/processor/src/extractors/zeromem_extractor.py` is the crux of "zero token":

```python
class ZeroMemExtractor:
    def __init__(self) -> None:
        self._nlp: Any = None
        self._gliner: Any = None

    def _get_nlp(self) -> Any:
        if self._nlp is None:
            import spacy
            self._nlp = spacy.load("en_core_web_trf")
        return self._nlp

    def _get_gliner(self) -> Any:
        if self._gliner is None:
            from gliner import GLiNER
            self._gliner = GLiNER.from_pretrained("urchade/gliner_small-v2.1")
        return self._gliner
```

Two extractors run in sequence and their outputs are merged:
- **spaCy `en_core_web_trf`** — general NER (PERSON, ORG, GPE, DATE, etc.)
- **GLiNER** (zero-shot NER) — catches domain concepts spaCy's fixed label set misses (`_GLINER_LABELS = ["person","organization","location","concept","event","product","facility","topic"]`)

Both are lazy-loaded (heavy transformer weights only load on first use, not at process boot — important given the "8 GB workstation" constraint documented in `prerequisites.md`).

Crucially, **co-occurrence weighting** is computed here, directly implementing the paper's edge-weighting formula:

```python
# w(d,e) = c(e,d) / Σ_e' c(e',d)
total = max(sum(entity_counts.values()), 1)
entity_context_weights: dict[str, float] = {
    eid: count / total for eid, count in entity_counts.items()
}
```

This weight is later written onto the `CO_OCCURRED_IN` edge (`link_entity_to_context(entity.id, context_id, tenant_id, weight)`), giving Personalized PageRank a signal for how "central" an entity is to a given chunk.

### 3.2 The pipeline orchestration

`ProcessingPipeline.process()` in `services/processor/src/processor/pipeline.py` — its own docstring makes the zero-token intent explicit:

```python
"""V3 Zero-Mem processing pipeline.

Stages
------
1. Schema validation  — validates the RawEventEnvelope; raises SchemaViolationError → DLQ.
2. Deduplication      — Redis SHA-256 check; silently drops duplicates.
3. ZeroMem extraction — NER-based entity extraction (spaCy + GLiNER, zero LLM calls):
     a. Create ContextUnit
     b. ZeroMemExtractor.extract() → entities + co-occurrence weights
     c. Persist ContextUnit node + CO_OCCURRED_IN edges in Neo4j
     d. Link to previous ContextUnit (NEXT_CONTEXT) for same source
     e. Index ContextUnit vector in Qdrant via ContextUnitIndexer (BGE-M3)
     f. Insert temporal record in Postgres via TemporalStore
4. Entity resolution  — Qdrant vector blocking + Neo4j structural matching.
5. Graph persistence  — atomic Neo4j write of Entity + Relationship nodes.
6. Alert publishing   — Kafka analyst-alerts if extraction_confidence > 0.5.
"""
```

The temporal bucketing IDs are derived **deterministically without external state** — a design that avoids a coordination service:

```python
def _assign_temporal_ids(tenant_id, source, now, event_id):
    def _h(key: str) -> str:
        return hashlib.sha256(key.encode()).hexdigest()[:12]
    ts = int(now.timestamp())
    domain = urlparse(source or "").netloc or "unknown"
    session_id = _h(f"{tenant_id}:{now.date().isoformat()}")        # daily bucket
    episode_id = _h(f"{tenant_id}:{domain}:{ts // 3600}")           # hourly, per-source
    window_id  = _h(f"{tenant_id}:{ts // 900}")                     # 15-minute bucket
    return session_id, episode_id, window_id, event_id
```

This gives the coarse-to-fine hierarchy (`episode → window → turn`) the temporal retriever later walks — entirely hash-derived, no sequence generator, no lock contention.

### 3.3 Dual-view retrieval — the paper's core mechanism

**Relational view** (`src/retrieval/relational.py`) implements entity-anchored multi-hop PPR:

```python
async def retrieve(self, profile, tenant_id, d_max=3, top_k=20):
    anchor_ids = await self._align_entities(profile, tenant_id, top_k=10)
    if not anchor_ids:
        return []
    try:
        results = await self._ppr_retrieve(anchor_ids, tenant_id, d_max, top_k)
        if results:
            return results
    except Exception as exc:
        logger.warning("apoc_ppr_failed_falling_back_to_bfs", extra={"error": str(exc)})
    return await self._bfs_retrieve(anchor_ids, tenant_id, top_k)
```

The APOC query is a genuinely localized PPR — it constrains the subgraph to a k-hop neighborhood *before* running PageRank, which is the specific optimization the paper calls for to keep latency bounded as the graph scales:

```cypher
MATCH (anchor:Entity) WHERE anchor.id IN $anchor_ids AND anchor.tenant_id = $tenant_id
CALL apoc.path.subgraphNodes(anchor, {
    maxLevel: $d_max,
    relationshipFilter: 'CO_OCCURRED_IN',
    labelFilter: '+ContextUnit|+Entity'
}) YIELD node
WITH collect(DISTINCT node) AS sub_nodes
CALL apoc.algo.pageRankWithConfig(sub_nodes, {dampingFactor: $gamma, iterations: 20})
YIELD node AS n, score
WHERE 'ContextUnit' IN labels(n) AND n.tenant_id = $tenant_id
RETURN n.id AS context_id, n.text AS text, score
ORDER BY score DESC LIMIT $top_k
```

**Temporal view** (`src/retrieval/temporal.py`) queries Postgres episode buckets first, resolving natural-language temporal cues via `dateparser`, and only falls back to plain recency:

```python
if profile.temporal_cues:
    episode_ids = _cue_to_episode_ids(profile.temporal_cues, tenant_id)
    for eid in episode_ids:
        ids = await self._store.query_episode_neighbors(eid, tenant_id, limit=top_k)
```

It explicitly **skips itself** for pure entity queries to avoid polluting fusion (`if not profile.temporal_cues and profile.route == "relational": return []`).

**Query routing** (`src/retrieval/profiler.py`) classifies before either view runs, purely via spaCy entity typing — no LLM:

```python
has_entities = bool(anchor_texts)
has_temporal = bool(temporal_cues)
if has_entities:
    route = "relational"
    d_max = 2 if has_temporal else 3
else:
    route = "local"
    d_max = 2
```

**Fusion** (`src/retrieval/fusion.py`) is route-biased min-max normalization + weighted blend — again zero LLM:

```python
if profile.route == "relational":
    rho = 0.7
else:
    rho = 0.3
combined = rho * rel_norm.get(cid, 0.0) + (1 - rho) * temp_norm.get(cid, 0.0)
...
fused = [c for c in fused if c.score >= 0.05]   # drop noise from temporal recency nomination
```

**Calibration** (`src/calibration/calibrator.py`) is the paper's bounded-evidence step — deduplicate near-identical spans, then hard-cut on a token budget approximated as `l_max * 4` chars:

```python
token_budget = l_max * _CHARS_PER_TOKEN
for ctx in deduped:
    if used + len(ctx.text) > token_budget:
        break
    result.append(ctx)
    used += len(ctx.text)
```

### 3.4 Where the LLM is *actually* still invoked

Per the paper's design, the LLM should only appear at final synthesis. In the current code, that boundary is **partially honored**:

- `POST /search` and `POST /query/expand` (Processor `main.py`) never call an LLM — confirmed by `test_echarts_drilldown_pipeline.py`'s explicit assertion `assert "token" not in data or data.get("tokens", 0) == 0`.
- `BriefingScriptGenerator` (`src/briefing/script_generator.py`) **does** call Ollama directly for the spoken-briefing synthesis step — the one place LLM usage is architecturally sanctioned. But its docstring flags a known gap: *"the GraphRAG CommunitySummarizer content source was removed. The natural V3 replacement is calibrated R(q) context arrays — treat as follow-on work after Phase 6"* — i.e., right now briefings fall back to a placeholder script rather than consuming the dual-view retrieval output, which is a genuine incompleteness against the paper's design.
- A stale `services/processor/src/llm/extractor.py` (pydantic-ai based, V2-era) still exists in the tree but is **not imported by any V3 code path** — the gap matrix flags this explicitly: *"not imported by any V3 path but will fail if imported"* — dead code that should be deleted to avoid accidental reintroduction of LLM calls into the ingest hot path.

---

## 4. Challenges in the Zero-Mem Implementation & Real-World Approaches

### 4.1 APOC PPR at scale

**Challenge:** `apoc.algo.pageRankWithConfig` running per-search on a live subgraph is fine at small N, but `docs/V3/proposed-architecture.md` itself flags this: *"PPR Latency in Large Neo4j Graphs — slower response times as the graph scales beyond 10^6 nodes."* The current `_ppr_retrieve` already does the right first step (bounding via `apoc.path.subgraphNodes` before ranking), which is the standard mitigation — but there's no caching layer, so a repeated anchor query re-runs the full PPR pass every time.

**Real-world approach:** Add a short-TTL result cache keyed on `(tenant_id, sorted(anchor_ids), d_max)` in Redis (already in the stack for dedup) before hitting Neo4j. Precompute PPR scores incrementally on ingest for "hot" entities (high-degree nodes) rather than only at query time — this is the standard "materialized PPR" pattern used by production graph-RAG systems (e.g., Neo4j's own GDS incremental centrality jobs).

### 4.2 GLiNER/spaCy throughput vs. Kafka ingestion rate

**Challenge:** `ZeroMemExtractor.extract()` is a **synchronous, blocking** call inside an `async` pipeline step:

```python
extraction = self._zeromem_extractor.extract(text, context_id, envelope.tenant_id)
```

No `await`, no thread-pool offload. On a single asyncio event loop, one large document's spaCy+GLiNER inference blocks all other coroutines on that worker, defeating the concurrency the Kafka consumer's `poll()`-based loop was designed for.

**Real-world approach:** Wrap NER calls in `asyncio.get_event_loop().run_in_executor(process_pool, ...)`, or move extraction fully into the Celery worker path (which the codebase already supports via `CELERY_ENABLED`) and set `--concurrency` on `processor-worker` to actually parallelize CPU-bound NER across worker processes rather than a single event loop thread. The `docs/V3/V3-implementation-plan.md` even calls this out: *"GLiNER ingestion batching: ensure GLiNER runs in batched tensor mode rather than single-text inference."* Batching multiple `ContextUnit`s per model call (rather than one HTTP event = one inference call) is the standard throughput fix.

### 4.3 Fail-open degrades silently into "zero entities"

**Challenge:** if GLiNER throws, the pipeline swallows it (`except Exception: logger.exception(...)`) and continues with whatever spaCy found — reasonable resilience, but there's no metric distinguishing "GLiNER genuinely found nothing" from "GLiNER crashed." Same fail-open pattern exists in `TemporalStore` and vector indexing (`try/except Exception: logger.exception(...)` with no re-raise) — good for uptime, bad for silent data loss over time.

**Real-world approach:** Emit a distinct Prometheus counter per fail-open branch (`processor_gliner_failures_total`, `processor_temporal_insert_failures_total`) rather than relying on log-line greps, and alert on sustained non-zero rates — this is standard "graceful degradation with SLO burn-rate alerting" practice, and the codebase already has the Prometheus scaffolding (`GRAPH_WRITE_ERRORS`, `CONTEXT_UNITS_CREATED`) to extend.

### 4.4 Entity resolver still depends on Ollama embeddings, not BGE-M3

**Challenge:** `EntityResolver._embed()` (`src/resolution/resolver.py`) calls `OLLAMA_URL/api/embeddings` with `nomic-embed-text` — this is a **leftover LLM-adjacent dependency** in an otherwise zero-token path, and it's inconsistent with `ContextUnitIndexer`, which correctly uses local `BGEM3FlagModel`. The gap matrix flags this directly: *"EntityResolver still uses Ollama nomic-embed-text (falls back to hash); should migrate to BGE-M3 for consistency."*

**Real-world approach:** Consolidate on one embedding backend. Since `ContextUnitIndexer.encode()` already wraps `BGEM3FlagModel`, the resolver should call the same class (shared model instance to avoid double GPU/CPU memory footprint) instead of round-tripping to Ollama over HTTP for every entity resolution.

### 4.5 Temporal cue parsing is a soft dependency with graph-hash coupling

**Challenge:** `_cue_to_episode_ids` in `temporal.py` imports `dateparser` lazily and, on failure to parse, silently treats the cue as "now" — this can silently misroute a query like "in 2019" to today's episode bucket. It also **duplicates** the exact hash formula used at ingest time (`f"{tenant_id}:unknown:{ts // 3600}"`), which is a footgun: if the ingest-side domain-hashing logic in `_assign_temporal_ids` ever changes, this retrieval-side copy will silently desync and stop matching episodes.

**Real-world approach:** Extract the episode-hash function into one shared module imported by both `pipeline.py` and `temporal.py` (single source of truth), and log (not silently substitute) when a temporal cue fails to parse, so query-time misrouting is observable rather than invisible.

### 4.6 Postgres and Neo4j can drift (dual-write without transaction)

**Challenge:** `ContextUnit` gets written to **three** independent stores per event — Neo4j (`upsert_context_unit`), Qdrant (`upsert_to_qdrant`), Postgres (`insert_context_unit_temporal`) — each wrapped in its own try/except with no cross-store rollback. A Neo4j success + Postgres failure leaves a `ContextUnit` node with no temporal-hierarchy row, silently degrading temporal retrieval for that unit forever (no retry queue).

**Real-world approach:** This is the classic "polyglot persistence" consistency problem; the standard fix is an outbox pattern — write the ContextUnit once to a durable log (Kafka already exists for this) and have per-store consumers (Neo4j writer, Qdrant indexer, Postgres writer) each independently reconcile from that log with their own retry/backoff, rather than three inline try/excepts inside one request path. Given Kafka is already central to this system, splitting `processor-events` into per-sink reconciliation consumers is a natural extension rather than new infrastructure.

---

## 5. Delivery: Current Structure and How to Make It More User-Friendly

### 5.1 What Delivery currently is

The Delivery layer (`services/delivery/src/app/explorer/page.tsx`) is a single search-first canvas:

```tsx
<EChartsGraphCanvas
  nodes={nodes}
  links={links}
  onNodeSelect={handleNodeSelect}
  onNodeDrillDown={handleNodeDrillDown}
/>
<SourceTracePane selectedNode={selectedNode} onClose={...} />
<PipelineProgressToast query={currentSearchQuery} toastState={toastState} .../>
```

- **Graph canvas** — `EChartsGraphCanvas.tsx`, a force-directed ECharts `series.type: "graph"` with click (inspect) and double-click (drill-down expansion) handlers.
- **Inspector** — `SourceTracePane.tsx`, a slide-out right panel showing raw context text, relevance score, source ID, timestamp for a single selected node.
- **Ingestion feedback** — `PipelineProgressToast.tsx`, a bottom-right floating card listing the 8 pipeline stages with live status icons driven by `usePipelineEvents`.
- **Realtime growth** — `useRealtimeNodes.ts` merges alert-driven new entities into the canvas without a full re-search.

This is functionally solid — the search→graph→realtime loop works — but the **information architecture is thin**: there's exactly one view (a global force graph), no persistent navigation, no saved state, and analytical framing (what the paper calls "final synthesis") is entirely absent from the UI.

### 5.2 Concrete gaps versus industry-standard graph/BI tooling

| Gap | Evidence in code | Industry pattern it's missing |
|---|---|---|
| **No BLUF / synthesis surface** | `explorer/page.tsx` renders only nodes+edges; `context_units` are fetched but only shown per-node in `SourceTracePane`, never aggregated | Palantir Gotham, Maltego, and Splunk all lead with a "so what" summary panel before the graph — the V2 `AssessmentPanel` concept documented in `docs/agent-contexts/gap-matrix.md` was built for exactly this but is orphaned outside the V3 path |
| **No global graph legend / stats** | `EChartsGraphCanvas.tsx` builds `legend` from whatever categories happen to be in the current result set, with no counts, no toggle-to-filter-by-category | Neo4j Bloom, Linkurious, and Gephi all show category counts and let users toggle visibility per type from the legend, not just color-code |
| **No search history / saved views** | `useState` for `searchQuery` only; nothing persisted, no `localStorage`/backend saved-search entity | Standard in Kibana/Grafana Explore — "recent searches" and "save this view" are baseline expectations |
| **Single force-layout, no layout switcher** | Only `layout: 'force'` is configured in `EChartsGraphCanvas` | Gephi/Cytoscape expose hierarchical, circular, and grid layouts; force layout alone becomes unreadable above ~150 nodes even with `roam: true` |
| **Loading/empty states are minimal** | Empty state is one static paragraph in `explorer/page.tsx`; no example queries beyond static text on the landing page | Good empty states (Notion, Linear) actively suggest next actions — e.g., surfacing recently-added entities or trending communities instead of a blank canvas |
| **Confidence/score not visually legible at a glance** | `symbolSize` only reflects `depth`, not `confidence`; the confidence value only appears in the tooltip and the inspector | Standard OSINT tooling (Maltego "weight" visualization) maps confidence to opacity or border style so low-confidence nodes are visually distinguishable without a click |
| **No multi-tenant / user account chrome** | `NEXT_PUBLIC_TENANT_ID` is a build-time env var, not a UI-selectable identity | Even single-tenant dev tools show *whose* workspace/session this is; there is currently no tenant switcher or session indicator in the header |
| **Error states are toast-only, ephemeral** | `PipelineProgressToast` error card is dismissible with no persistent error log | Standard practice (Datadog, Grafana) keeps a small persistent "issues" bell/log so a dismissed error isn't lost forever |
| **Briefing feature is a disconnected side panel, not integrated into the graph flow** | `BriefingPanel.tsx` is a separate component fetched from `/api/briefings`, with no link between "briefing mentions X" and "click through to X's graph node" | Audio/summary features in modern BI tools (Notion AI, Glean) are contextual — generated *from* the current view and deep-linked back into it |

### 5.3 Recommended improvements, grounded in what already exists

1. **Add a synthesis/BLUF strip above the canvas**, populated from the `context_units` array `POST /search` already returns (`calibrated` R(q) output) — this data is *already computed* server-side (`EvidenceCalibrator`) and currently thrown away except per-node. A simple 2–3 sentence extractive summary of the top-scored `context_units` would surface the paper's "final synthesis" concept without any new backend work.

2. **Legend-as-filter**: extend `EChartsGraphCanvas`'s `legend` config with `selected` state wired to category checkboxes, and show a count badge per category (`uniqueCategories.map(cat => ({name: cat, count: nodes.filter(n => n.category === cat).length}))`) — this is a small addition to existing code, not a new subsystem.

3. **Confidence-driven visual encoding**: map `node.value` (currently `entity.confidence`) to `itemStyle.opacity` in addition to color, so low-confidence/ambiguous entities visually recede — directly usable since `confidence` is already on every `EChartsNode`.

4. **Persist recent searches client-side** (React state → `sessionStorage`, since `localStorage` isn't available in some artifact contexts but is fine in the real Next.js app) and render them as chips under the search bar on the empty-state screen, replacing the static "Try: Sundar Pichai..." hint text.

5. **Reconnect `BriefingPanel` to the graph**: when a briefing script mentions an entity name, make it a clickable chip that calls `router.push('/explorer?q=' + name)` — this closes the loop between the "lean-back" audio modality and the graph modality that `AI BI Platform Architecture & Business.md` explicitly designed for but which the two components (`BriefingPanel.tsx`, `explorer/page.tsx`) don't currently reference each other.

6. **Layout switcher**: ECharts' `graph` series supports `layout: 'none' | 'circular' | 'force'` natively — exposing a 3-button toggle costs little and immediately improves legibility on large result sets, which the current force-only config does not handle gracefully.

7. **Persistent error/notification log**: extend `PipelineProgressToast`'s dismiss handler to push into a small ring-buffer store (even just React context) rendered as a bell icon in the header, rather than discarding error state on dismiss.

---

## 6. Summary

The codebase is a genuine, working implementation of the Zero-Mem paradigm for the *ingestion and retrieval* path — spaCy+GLiNER extraction, ContextUnit/Entity graph, Qdrant BGE-M3 indexing, Postgres temporal hierarchy, APOC PPR relational retrieval, and calibrated evidence fusion are all real, tested code, not just architecture docs. The main gaps are (a) the LLM-synthesis boundary at Briefings isn't yet wired to the new retrieval output, (b) a few leftover Ollama/pydantic-ai dependencies from the V2 LLM-extraction era create inconsistency, and (c) fail-open error handling across three parallel data stores (Neo4j/Qdrant/Postgres) risks silent drift without an outbox-style reconciliation mechanism. Delivery, meanwhile, is a functionally complete search-to-graph loop but stops short of turning the Processor's calibrated context array into an actual synthesized answer for the analyst — the single highest-leverage UX improvement available today, since the underlying data is already computed and simply not surfaced.
