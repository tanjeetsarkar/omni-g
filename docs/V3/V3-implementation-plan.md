# Plan: Zero-Mem (V3) Integration

**TL;DR**: Fully replace V2's LLM extraction + intelligence cycle with Zero-Mem's zero-token paradigm — NER-based extraction → entity-context graph → dual-view retrieval (PPR + temporal hierarchy) → bounded calibration → LLM only at Delivery final synthesis. Adds Postgres, BGE-M3 embeddings, and APOC PPR to the stack.

---

## Decisions

- Zero-Mem **fully replaces** V2 intelligence cycle (KIQ/assessment/hypothesis deprecated)
- Neo4j schema: **replace** Entity-first with ContextUnit-first (`:ContextUnit` primary, `:Entity` detected entities)
- Temporal hierarchy: **Postgres** added to stack
- GraphRAG + CommunitySummarizer: **deprecated and removed**
- BGE-M3: **direct FlagEmbedding Python library** in Processor image
- LLM remains ONLY for final synthesis (Delivery reader) and briefings

---

## Phase 1: Infrastructure & Dependencies *(blocking — must come first)*

1. **`infrastructure/docker-compose.yml`** — add `postgres:16-alpine` service (port 5432, `POSTGRES_DB/USER/PASSWORD`); add `NEO4J_PLUGINS=["apoc"]` env var to neo4j service to enable APOC PPR
2. **`services/processor/pyproject.toml`** — add `spacy>=3.8`, `gliner>=0.2`, `FlagEmbedding>=1.3`, `asyncpg>=0.30`; remove `stix2==3.0.1` (still present despite gap-matrix claiming removal), `langchain==0.3.10`, `instructor>=1.7.0`, `pydantic-ai-slim[openai]==1.104.0`
3. **`services/processor/Dockerfile`** — add `python -m spacy download en_core_web_trf` model download layer

---

## Phase 2: V2 Model Deprecation *(parallel with Phase 3)*

4. **`src/models/entities.py`** — remove `SourceClassification`, `ReliabilityRating`, `CredibilityRating`, `CollectedEvidence`, `ConfidenceBand`, `Assessment`, `CollectionGap`, `Hypothesis`, `HypothesisBand`; strip `collected_evidence`, `hypotheses`, `assessment`, `kiq_id` from `ExtractionResult`; add `ContextUnit` model (`id, text, source_id, tenant_id, session_id, episode_id, window_id, created, metadata`)
5. **Delete from `src/processor/`**: `assessment.py`, `assessment_publisher.py`, `hypothesis.py`, `evidence_publisher.py`
6. **Delete `src/graphrag/`** — entire directory (`indexer.py`, `community.py`, `summarizer.py`)
7. **`src/processor/pipeline.py`** — strip Steps 3.6 (evidence), 3.7 (assessment), 3.9 (hypothesis/reanalysis) and all corresponding imports from `ProcessingPipeline`
8. **Delete obsolete tests**: `test_assessment.py`, `test_extractor.py` (LLM-based), `test_briefing_scheduler.py`

---

## Phase 3: ContextUnit-First Graph Schema *(parallel with Phase 2)*

9. **`src/graph/schema.py`** — add `:ContextUnit` unique constraint + indexes on `(tenant_id)`, `(source_id)`, `(created)`, composite `(tenant_id, episode_id, created)`; existing `:Entity` indexes kept
10. **`src/graph/persistence.py`** — add `upsert_context_unit()`, `link_entity_to_context()` (`CO_OCCURRED_IN` edge with weight), `link_adjacent_contexts()` (`NEXT_CONTEXT` edge); remove community-summary write paths
11. **New `src/graph/temporal_store.py`** — asyncpg-backed: tables `context_units_temporal(id, tenant_id, session/episode/window/turn_id, created_at)` and `temporal_episodes`; `insert_context_unit_temporal()`, `query_episode/window/turn_neighbors()`

---

## Phase 4: Zero-Token Extractor *(depends on Phases 2 + 3)*

12. **New `src/extractors/zeromem_extractor.py`** — `ZeroMemExtractor`: loads spaCy `en_core_web_trf` + GLiNER; `extract(text, context_id, tenant_id) -> ExtractionResult`; computes co-occurrence weight w(d,e) = c(e,d) / sum_e'(c(e',d)) per eq. (4); zero LLM calls
13. **New `src/indexers/vector.py`** — `ContextUnitIndexer`: loads `BGEM3FlagModel`; `encode(texts) -> ndarray`; `upsert_to_qdrant(context_id, embedding, payload, tenant_id)` into collection `context_units_{tenant_id}`
14. **`src/processor/pipeline.py`** — replace Step 3 (LLM extraction) with: `ZeroMemExtractor.extract()` → persist `ContextUnit` → `link_adjacent_contexts()` → `link_entity_to_context()` → `ContextUnitIndexer.upsert_to_qdrant()` → `TemporalStore.insert_context_unit_temporal()` → existing `EntityResolver` for entity dedup

---

## Phase 5: Dual-View Retrieval Engine *(depends on Phase 4)*

15. **New `src/retrieval/profiler.py`** — `QueryProfiler.profile(query) -> QueryProfile`; spaCy entity extraction; classifies route as `"relational"` (entity-heavy) or `"local"` (temporal); sets `D_max`, `keywords`, `temporal_cues`
16. **New `src/retrieval/relational.py`** — `RelationalRetriever.retrieve(profile, tenant_id, d_max, top_k)`; entity alignment via Qdrant cosine (eq. 8) → activation propagation through `CO_OCCURRED_IN` edges (eq. 9) → APOC PPR with γ=0.6 (eq. 10); graceful fallback to Python BFS if APOC unavailable
17. **New `src/retrieval/temporal.py`** — `TemporalRetriever.retrieve(profile, tenant_id, top_k)`; coarse-to-fine `episode → window → turn → local_span` (eq. 11) via Postgres `TemporalStore`
18. **New `src/retrieval/fusion.py`** — `DualViewFusion.fuse(relational, temporal, profile, rho=0.6)`; per-view score normalization (eq. 12) → weighted blend (eq. 13) → evidence closure: graph bridges Ng + local span neighbors Nh (eq. 14) → dedup

---

## Phase 6: Evidence Calibration *(depends on Phase 5)*

19. **New `src/calibration/calibrator.py`** — `EvidenceCalibrator.calibrate(candidates, profile, l_max=4096) -> list[ScoredContext]` (eq. 15); filter by provenance/boundary → rank by subject+temporal+answer-type compatibility → token-budget cutoff → span deduplication

---

## Phase 7: Search Endpoint Update *(depends on Phase 6)*

20. **`src/processor/main.py`** — replace `_search_with_qdrant` with full dual-view pipeline: `QueryProfiler → parallel RelationalRetriever + TemporalRetriever → DualViewFusion → EvidenceCalibrator → R(q)`; update `SearchResponse` to include `context_units: list[ContextUnitPayload]`; keep `entities` + `relationships` for React Flow compatibility

---

Here are the updated **Phase 8** and **Phase 9** modules for your implementation plan, completely replacing React Flow in favor of **Apache ECharts** (`echarts` / `echarts-for-react`).

---

## Phase 8: Frontend Apache ECharts Canvas & Inspection Panel (`apps/web/`)

**Goal:** Replace React Flow with a high-performance Apache ECharts force-directed graph canvas for intuitive multi-hop drill-downs, connected to a slide-out React inspection sidebar.

### 1. Files to Modify / Create

* **Modify:** `apps/web/package.json`
* **Create:** `apps/web/components/canvas/EChartsGraphCanvas.tsx`
* **Create:** `apps/web/components/canvas/useEChartsGraphAdapter.ts`
* **Modify:** `apps/web/components/inspector/SourceTracePane.tsx`
* **Modify:** `apps/web/app/explorer/page.tsx`

### 2. Implementation Strategy & Code Base Changes

1. **Dependency Updates (`apps/web/package.json`):**
* Uninstall `@xyflow/react` / `reactflow`.
* Install `echarts` and `echarts-for-react`:
```bash
pnpm --filter web remove @xyflow/react
pnpm --filter web add echarts echarts-for-react

```




2. **Graph Data Transformation Adapter (`useEChartsGraphAdapter.ts`):**
* Convert Zero-Mem multi-hop API responses into ECharts-compliant `graph` option schemas.
* Map entity types (e.g., `FACILITY`, `PERSON`, `STUDY`, `CONCEPT`) to distinct node colors, sizes, and visual categories:
```typescript
export function transformToEChartsData(evidenceNodes: EvidenceNode[], edges: EvidenceEdge[]) {
  const nodes = evidenceNodes.map(node => ({
    id: node.id,
    name: node.label,
    symbolSize: node.depth === 0 ? 45 : node.depth === 1 ? 32 : 22,
    category: node.type,
    value: node.score,
    itemStyle: { color: getTypeColor(node.type) },
    rawContext: node.raw_text,
    sourceId: node.source_id,
    timestamp: node.created_at
  }));

  const links = edges.map(edge => ({
    source: edge.source_id,
    target: edge.target_id,
    value: edge.weight,
    lineStyle: { width: Math.max(1, edge.weight * 3), opacity: 0.6 }
  }));

  return { nodes, links };
}

```




3. **Apache ECharts Canvas Component (`EChartsGraphCanvas.tsx`):**
* Render ECharts with force-directed physics (`layout: 'force'`).
* Enable progressive multi-hop drill-down on click events and handle smooth focus transitions:
```tsx
import ReactECharts from 'echarts-for-react';

export function EChartsGraphCanvas({ nodes, links, onNodeSelect, onNodeDrillDown }) {
  const option = {
    tooltip: { trigger: 'item', formatter: '{b} ({c})' },
    legend: [{ data: ['FACILITY', 'PERSON', 'STUDY', 'CONCEPT'] }],
    series: [{
      type: 'graph',
      layout: 'force',
      data: nodes,
      links: links,
      roam: true,
      label: { show: true, position: 'right', formatter: '{b}' },
      force: { repulsion: 250, gravity: 0.1, edgeLength: 90, friction: 0.6 },
      emphasis: { focus: 'adjacency', lineStyle: { width: 4 } }
    }]
  };

  const onEvents = {
    click: (params: any) => {
      if (params.dataType === 'node') {
        onNodeSelect(params.data);
      }
    },
    dblclick: (params: any) => {
      if (params.dataType === 'node') {
        onNodeDrillDown(params.data.id);
      }
    }
  };

  return <ReactECharts option={option} onEvents={onEvents} style={{ height: '100%', width: '100%' }} />;
}

```




4. **Sidebar Trace Panel (`SourceTracePane.tsx`):**
* Keep rendering cleanly outside the Canvas in a Next.js / Tailwind floating drawer. When a user clicks a node in ECharts, display the un-summarized raw context, timestamps, confidence weights, and exact source references.



### 3. Validation Criteria & Test Suite

* **Unit Test:** `apps/web/tests/useEChartsGraphAdapter.test.ts`
* Assert multi-hop nodes correctly transform into ECharts `data` and `links` format.
* Assert root nodes ($D=0$) receive larger `symbolSize` than leaf nodes ($D=2, 3$).


* **UI Component Test:** `apps/web/tests/EChartsGraphCanvas.test.tsx`
* Render component with 200 nodes. Assert Canvas mounts without frame drops or DOM node inflation (verifying single `<canvas>` element rendering).
* Simulate single-click on node $\rightarrow$ verify `onNodeSelect` fires with full metadata payload.



---

## Phase 9: End-to-End Delivery Integration, Interactive Drill-Downs & Validation

**Goal:** Connect ECharts frontend interactions to the backend Zero-Mem retrieval engine and execute complete end-to-end performance and accuracy validation.

### 1. Files to Modify / Create

* **Modify:** `services/delivery/src/routes/query.py`
* **Modify:** `apps/web/app/explorer/page.tsx`
* **Create:** `tests/e2e/test_echarts_drilldown_pipeline.py`

### 2. Implementation Strategy & Code Base Changes

1. **Interactive Multi-Hop API Route (`services/delivery/src/routes/query.py`):**
* Support dynamic context expansions triggered directly from ECharts double-clicks:
* `POST /api/v1/query/expand`: Takes `{ "anchor_node_id": "hospital_123", "current_depth": 1, "target_depth": 2 }`.
* Runs localized Personalized PageRank (PPR) around `hospital_123` and returns incremental nodes/links to merge into ECharts state without full page refreshes.




2. **Frontend State Merging (`apps/web/app/explorer/page.tsx`):**
* Handle dynamic node insertion when `onNodeDrillDown` triggers:
```typescript
const handleDrillDown = async (nodeId: string) => {
  const incrementalData = await api.expandNode({ anchor_node_id: nodeId, current_depth: depth });
  setGraphState(prev => ({
    nodes: deduplicateNodes([...prev.nodes, ...incrementalData.nodes]),
    links: deduplicateLinks([...prev.links, ...incrementalData.links])
  }));
};

```




3. **End-to-End Benchmarking & Token Zeroing Verification:**
* Validate that all incremental expansions execute via non-generative graph traversals without making LLM calls.



### 3. Validation Criteria & Test Suite

* **E2E Automation Test:** `tests/e2e/test_echarts_drilldown_pipeline.py`
1. Trigger query `"Cancer hospitals"` $\rightarrow$ assert ECharts receives level 0 root node (e.g., *Johns Hopkins Hospital*).
2. Simulate expansion on *Johns Hopkins Hospital* $\rightarrow$ assert API returns level 1 nodes (e.g., *Dr. Smith*, *Oncology Dept*).
3. Simulate expansion on *Dr. Smith* $\rightarrow$ assert level 2 nodes (e.g., *Immunotherapy Trial 2025*) appear in graph state.
4. Verify **0 indexing/memory tokens** were logged across all expansion cycles.
5. Assert backend expansion response latency remains **$< 120\text{ms}$** per drill step.

---

## Phase 10: Tests & Documentation *(last)*

29. **New processor tests**: `test_zeromem_extractor.py`, `test_vector_indexer.py`, `test_retrieval_profiler.py`, `test_retrieval_relational.py`, `test_retrieval_temporal.py`, `test_fusion.py`, `test_calibrator.py`; update `test_graph.py` (add ContextUnit, remove community-summary); update `test_consumer.py`, `test_celery_dispatch.py` for new pipeline stages
30. **`docs/agent-contexts/gap-matrix.md`** — add V3 section: V2 deprecation status, Zero-Mem integration per phase, remaining gaps

---

## Relevant Files

### Core processor changes
- `services/processor/pyproject.toml`
- `services/processor/Dockerfile`
- `services/processor/src/models/entities.py`
- `services/processor/src/graph/schema.py`
- `services/processor/src/graph/persistence.py`
- `services/processor/src/processor/pipeline.py`
- `services/processor/src/processor/main.py`

### New processor files
- `services/processor/src/extractors/zeromem_extractor.py`
- `services/processor/src/indexers/vector.py`
- `services/processor/src/graph/temporal_store.py`
- `services/processor/src/retrieval/profiler.py`
- `services/processor/src/retrieval/relational.py`
- `services/processor/src/retrieval/temporal.py`
- `services/processor/src/retrieval/fusion.py`
- `services/processor/src/calibration/calibrator.py`

### Files to delete (processor)
- `services/processor/src/graphrag/` (entire dir)
- `services/processor/src/processor/assessment.py`
- `services/processor/src/processor/assessment_publisher.py`
- `services/processor/src/processor/hypothesis.py`
- `services/processor/src/processor/evidence_publisher.py`

### Core delivery changes
- `services/delivery/src/app/dashboard/page.tsx`
- `services/delivery/src/types/entities.ts`
- `services/delivery/src/app/api/query/route.ts`
- `services/delivery/src/components/graph/KnowledgeGraph.tsx`

### Files to delete (delivery)
- `services/delivery/src/components/assessment/` (entire dir)
- `services/delivery/src/hooks/useAssessmentEvents.ts`
- `services/delivery/src/app/api/assessments/route.ts`
- `services/delivery/src/types/assessment.ts`

### Infrastructure
- `infrastructure/docker-compose.yml`

---

## Verification

1. `docker compose --profile core up` — Postgres and Neo4j+APOC start cleanly
2. `uv run pytest services/processor/tests/ -x` — all new tests pass
3. `pnpm test` in delivery — passes with assessment components removed
4. Manual: ingest event → `:ContextUnit` node in Neo4j + temporal row in Postgres
5. Manual: `POST /search` → response includes `context_units` array with `score` and `entity_ids`
6. Manual: search in delivery → click entity node → `ContextUnitNode` expands inline

---

## Parallelism

- Phase 1 blocks all others
- Phases 2 and 3 can run in parallel after Phase 1
- Phase 4 requires Phases 2 and 3
- Phase 5 requires Phase 4
- Phase 6 requires Phase 5
- Phase 7 requires Phase 6
- Phase 8 removals (steps 21–25) can run independently after Phase 2 decisions
- Phase 8 frontend updates (steps 26–28) require Phase 7
- Phase 9 runs last

---

## Further Considerations

1. **Briefings input gap**: `CommunitySummarizer` was the briefing content source. With GraphRAG gone, the briefing script generator needs a new source — calibrated `R(q)` context arrays are the natural replacement. Treat as follow-on work after Phase 6. The Celery Beat infrastructure for briefings is kept.
2. **APOC fallback**: `relational.py` PPR must degrade gracefully to Python BFS (mirroring the existing `CommunityDetector` pattern) for local dev where APOC may not be loaded.
3. **`stix2` drift**: The gap-matrix claimed it was removed but `pyproject.toml` still has `stix2==3.0.1` — Phase 1 removes it.
4. **GLiNER ingestion batching**: When processing high-velocity Kafka streams in `zeromem_extractor.py`, ensure GLiNER runs in batched tensor mode rather than single-text inference to maximize throughput.
5. **Neo4j localized PPR execution**: In `relational.py` (PPR engine), pass explicit sub-graph node IDs to APOC rather than running PageRank globally across the entire database to keep latency low as the graph grows beyond 10^6 nodes.
