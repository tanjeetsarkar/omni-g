# Omni-G Master Engineering & Architecture Roadmap

This document serves as the **unified master technical roadmap** for the overhaul of Omni-G. It synthesizes the **Figma-Style Canvas UI/UX Uplift**, the **Zero-Mem Processor Alignment**, and the **Micro/Mu-Inspired Aggregator Agent Governance Framework** into an actionable, phase-by-phase execution plan.

---

## Architecture Overview & Service Alignment

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                       1. AGGREGATOR SERVICE (Go)                                         │
│                                                                                                         │
│  ┌─────────────────────────┐   ┌────────────────────────┐   ┌────────────────────────────────────────┐  │
│  │ Micro-Inspired Services │   │ Autonomous Agents      │   │ 9-Stage Tool Governance Harness        │  │
│  │ - News, Search, Weather │   │ - PollerAgent (Interval│──►│ (Register, Advertise, Select, Validate,│  │
│  │ - Feeds/RSS, Location   │   │ - WatcherAgent (Streams│   │  Permission, Execute, Observe,         │  │
│  └─────────────────────────┘   └────────────────────────┘   │  Normalize, Return Loop)               │  │
│                                                             └───────────────────┬────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────────┼───────────────────────┘
                                                                                  │ Enriched RawEvents
                                                                                  ▼ (Kafka: raw-feed)
┌─────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                       2. PROCESSOR SERVICE (Python)                                      │
│                                                                                                         │
│  ┌─────────────────────────────────┐   ┌────────────────────────────────┐   ┌────────────────────────┐  │
│  │ Non-Generative Ingestion (0 Token)│   │ Dual-View Storage Layer        │   │ Dual-View Retrieval    │  │
│  │ - spaCy / GLiNER Extractor      │──►│ - Neo4j (:ContextUnit, :Entity)│──►│ - Localized PPR (APOC) │  │
│  │ - BGE-M3 Dense Vector Embedder  │   │ - Qdrant (1024-dim Embeddings) │   │ - Top-K Branch Pruning │  │
│  └─────────────────────────────────┘   └────────────────────────────────┘   └───────────┬────────────┘  │
└─────────────────────────────────────────────────────────────────────────────────────────┼───────────────────────┘
                                                                                  │ Calibrated Evidence
                                                                                  ▼ (/api/v1/query)
┌─────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                    3. DELIVERY & UI CANVAS (Next.js 15)                                  │
│                                                                                                         │
│  ┌──────────────────────────────────┐   ┌───────────────────────────────┐   ┌────────────────────────┐  │
│  │ Figma-Style Immersive Canvas     │   │ Custom Rich Nodes (ECharts)   │   │ Non-Blocking Drawer    │  │
│  │ - Top Floating Search Pill       │──►│ - Type Pills, Title, Links    │──►│ - Exact Text Snippets  │  │
│  │ - Top-Right Settings Gear        │   │ - Stale State Purge Engine    │   │ - Source Provenance    │  │
│  └──────────────────────────────────┘   └───────────────────────────────┘   └────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────────────────────────────────┘

```

---

## Track 1: Delivery & UI/UX Canvas Uplift (`apps/web/`)

**Goal:** Transform the UI into a **Figma-style infinite graph canvas** using Apache ECharts WebGL, removing boxy cards and legacy borders. Enforce custom rich visual nodes, zero-stale state canvas management, and mobile-friendly slide-in bottom sheets.

### Module 1.1: Dependency Cleanup & Store Architecture

* [ ] **Uninstall Legacy Canvas Dependencies:**
* Remove `@xyflow/react` and `reactflow` from `apps/web/package.json`.




* [ ] **Install WebGL & Animation Dependencies:**
* Add `echarts`, `echarts-for-react`, `framer-motion`, `clsx`, and `tailwind-merge`.




* [ ] **Implement Global Stale-Free Canvas Store (`apps/web/src/store/useGraphExplorerStore.ts`):**
* Create `clearCanvas()` action that invokes `chart.clear()` immediately upon query submit or settings adjustment to eliminate stale graph persistence.


* Store depth ($D_{\max} \in [1, 4]$), relevance threshold ($\tau \in [0.1, 1.0]$), and token cap ($L_{\max} \in [2048, 8192]$).





### Module 1.2: Figma-Style Floating UI Controls

* [ ] **Floating Search Pill (`apps/web/src/components/controls/FloatingSearchBar.tsx`):**
* Create top-center floating frosted-glass search bar (`backdrop-blur-md bg-background/70 shadow-2xl`).


* Add type-ahead autocomplete categorized by generalized entity tags (`FACILITY`, `PERSON`, `CONCEPT`, `STUDY`).


* Wire `Enter` keypress to trigger canvas clearing and query submission.




* [ ] **Floating Settings Gear Panel (`apps/web/src/components/controls/SettingsGearPanel.tsx`):**
* Top-right gear icon button opening a popover with visual tuning controls:
* Relevance Threshold Slider ($\tau$).


* Traversal Depth Dial ($D_{\max}$).


* Max Token Cap Slider ($L_{\max}$).







### Module 1.3: Custom Visual Card Nodes & Canvas Renderer

* [ ] **ECharts Graph Adapter (`apps/web/src/components/canvas/useEChartsGraphAdapter.ts`):**
* Transform API graph response nodes into rectangular visual card nodes (`symbol: 'roundRect'`, size `[170, 54]`).


* Format node interior using ECharts rich-text labels:
* Type badge pill (e.g. `FACILITY` in blue, `PERSON` in teal).


* Bold entity title (e.g. "Johns Hopkins Hospital").


* Sub-entity expansion counter (e.g. `+12 Doctors`).


* Human-readable source origin tag (e.g. `📍 PubMed Central`).






* [ ] **ECharts WebGL Fullscreen Canvas (`apps/web/src/components/canvas/EChartsGraphCanvas.tsx`):**
* Render graph using `type: 'graph'` and `layout: 'force'`.


* Configure single-click event (`chart.on('click')`) to populate the evidence drawer.


* Configure double-click event (`chart.on('dblclick')`) to call `/api/v1/query/expand` for dynamic multi-hop expansion.





### Module 1.4: Non-Blocking Floating Evidence Drawer

* [ ] **Responsive Evidence Panel (`apps/web/src/components/drawer/SourceTraceDrawer.tsx`):**
* Desktop ($> 1024\text{px}$): Floating right sidebar panel ($380\text{px}$ width).


* Mobile ($< 767\text{px}$): Framer Motion swipeable bottom-sheet drawer.


* Strips out database UUIDs and raw graph keys—renders strictly human-readable source metadata, timestamps, and unmodified raw text snippets.





---

## Track 2: Zero-Mem Knowledge Graph Alignment (`services/processor/`)

**Goal:** Fully align the Processor service with the Zero-Mem paradigm. Completely purge STIX 2.1 schemas in favor of generalized domain entities, achieve $0$ LLM token ingestion costs, and support Personalized PageRank (PPR) multi-hop graph traversals.

### Module 2.1: Ingestion & Non-Generative Extraction

* [ ] **Dependency Deprecation (`services/processor/pyproject.toml`):**
* Deprecate LLM-driven graph extraction prompts on ingestion.


* Add `spacy >= 3.7.0` (`en_core_web_trf`), `gliner >= 0.1.0`, `fastembed >= 0.3.0`, and `networkx >= 3.0`.




* [ ] **Zero-Token Entity Extractor (`services/processor/src/extractors/zeromem_extractor.py`):**
* Extract generalized entity types (`ORGANIZATION`, `PERSON`, `LOCATION`, `CONCEPT`, `FACILITY`, `STUDY`, `TREATMENT`) via spaCy/GLiNER without LLM API calls.


* Chunk incoming documents into context units ($V_d$) with exact character offset tracking.





### Module 2.2: Neo4j & Vector Storage Layer

* [ ] **Neo4j Cypher Schema Overhaul (`services/processor/src/indexers/graph_indexer.py`):**
* Remove STIX triple constraints.


* Persist nodes as `:ContextUnit` ($V_d$) and `:Entity` ($V_e$).


* Persist edges as `:CO_OCCURRED_IN` ($E_{de}$) and `:NEXT_CONTEXT` ($E_{dd}$) with human-readable source provenance attributes (`source_name`, `source_url`, `plugin_name`, `created_at`).




* [ ] **Dense Embedding Indexer (`services/processor/src/indexers/vector_indexer.py`):**
* Generate 1024-dimensional dense vectors for all $V_d$ context units locally using BGE-M3.


* Index vectors in Qdrant with payload links to Neo4j `source_id`.





### Module 2.3: Retrieval & Evidence Calibration Engine

* [ ] **Localized PPR Engine (`services/processor/src/retrieval/ppr_engine.py`):**
* Implement localized Personalized PageRank using Neo4j APOC plugins targeted at seed entity anchors.


* Support depth parameter $D_{\max}$ to walk $k$-hop paths along $E_{de}$ co-occurrence links.




* [ ] **Dynamic Relevance Pruning (`services/processor/src/api/routes/query.py`):**
* Accept `relevance_threshold` ($\tau$) parameter to dynamically prune edges where co-occurrence weight $w(d, e) < \tau$.




* [ ] **Bounded Evidence Calibrator (`services/processor/src/calibration/calibrator.py`):**
* Hard-cap retrieved context payload token length to $L_{\max}$ (default: 4096 tokens).


* Deduplicate overlapping text spans before handing context to the reader model.





---

## Track 3: Aggregator Ingestion Agents & Governance (`services/aggregator/`)

**Goal:** Refactor `services/aggregator` to adopt Micro/Mu-inspired domain services (**News, Search, Weather, Feeds, Location**) and wrap ingestion in **Autonomous Ingestion Agents** governed by a strict **9-Stage Production Tool Execution Lifecycle Harness**.

### Module 3.1: Enriched Envelope & Micro Services

* [ ] **RawEvent Contract Enrichment (`services/aggregator/pkg/models/event.go`):**
* Enforce non-null human-centric provenance fields: `source_name`, `source_url`, `plugin_name`, and `timestamp`.




* [ ] **Micro/Mu Domain Services (`services/aggregator/internal/services/`):**
* Implement **News Service Tool**: Pulls articles with publisher metadata, headlines, and publication dates.


* Implement **Search Service Tool**: Performs domain/web searches returning source URLs and extracted text snippets.


* Implement **Weather Service Tool**: Ingests temporal geospatial weather events.


* Implement **Feeds Service Tool**: Ingests structured RSS/JSON-RPC feeds.


* Implement **Location Service Tool**: Resolves physical locations to geospatial coordinates ($lat, long$).





### Module 3.2: 9-Stage Tool Governance Harness

* [ ] **Core Harness Engine (`services/aggregator/pkg/harness/harness.go`):**
* Implement the strict 9-stage execution lifecycle pipeline:


1.
**Register:** Validates tool JSON schema and risk levels.


2.
**Advertise:** Exposes active tools to agent registry.


3.
**Select:** Rejects execution if tool signature mismatches.


4.
**Validate:** Enforces argument schema checks (`pkg/harness/validator.go`).


5.
**Permission Check:** Enforces tenant access control (`pkg/harness/permission.go`).


6.
**Execute:** Executes tool in an isolated sandbox with circuit breakers.


7.
**Observe:** Emits Prometheus latency metrics and Loki traces.


8.
**Normalize:** Formats tool output into Zero-Mem compliant `RawEvent`.


9.
**Return Loop:** Emits event to Kafka `raw-feed` and returns control token.







### Module 3.3: Autonomous Ingestion Agents

* [ ] **Agent Runtime & Supervisor (`services/aggregator/pkg/agent/`):**
*
**PollerAgent (`poller.go`):** Executes background interval/cron fetches using tools registered in the Harness.


*
**WatcherAgent (`watcher.go`):** Maintains long-lived SSE/WebSocket streams with auto-reconnect backoff.


*
**AgentSupervisor (`supervisor.go`):** Monitors agent health, manages runtime lifecycle, and recovers failed agents.





---

## Track 4: Implementation Roadmap & Milestones

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ MILESTONE 1: Aggregator Harness & Ingestion Agents (Days 1–3)               │
├─────────────────────────────────────────────────────────────────────────────┤
│ MILESTONE 2: Zero-Mem Processor Ingestion & Neo4j Schema (Days 4–5)         │
├─────────────────────────────────────────────────────────────────────────────┤
│ MILESTONE 3: Localized PPR Retrieval & Dynamic Thresholding (Days 6–7)     │
├─────────────────────────────────────────────────────────────────────────────┤
│ MILESTONE 4: Delivery ECharts Canvas & Figma UI Controls (Days 8–10)       │
├─────────────────────────────────────────────────────────────────────────────┤
│ MILESTONE 5: End-to-End Governance Audit & Verification (Days 11–12)        │
└─────────────────────────────────────────────────────────────────────────────┘

```

### Phase Breakdown

#### Phase 1: Aggregator Contract & Governance (Days 1–3)

* [ ] Enforce `source_name` and `plugin_name` in `RawEvent` model.


* [ ] Implement 9-stage Tool Harness (`pkg/harness/`).


* [ ] Build News, Search, and Weather micro-services.


* [ ] Route `PollerAgent` and `WatcherAgent` through `Harness.InvokeTool()`.


* [ ] **Validation:** `go test ./pkg/harness/...` (Verify Stage 4 validation and Stage 5 permission rejections).



#### Phase 2: Processor Zero-Mem Core & Storage (Days 4–5)

* [ ] Add `spacy` and `gliner` to `pyproject.toml`; deprecate LLM graph parsing.


* [ ] Overhaul Neo4j Cypher scripts for generalized `:ContextUnit` and `:Entity` nodes.


* [ ] Configure Qdrant vector store with 1024-dim BGE-M3 local embeddings.


* [ ] **Validation:** Ingest 100 raw events via Kafka and verify **$0$ memory LLM token cost**.



#### Phase 3: PPR Multi-Hop Retrieval Engine (Days 6–7)

* [ ] Implement localized Personalized PageRank in `ppr_engine.py`.


* [ ] Add dynamic relevance threshold ($\tau$) edge pruning in `/api/v1/query`.


* [ ] Build `calibrator.py` to enforce token ceiling ($L_{\max} = 4096$).


* [ ] **Validation:** `pytest tests/test_multi_hop_retrieval.py` (Verify sub-150ms multi-hop response times).



#### Phase 4: Delivery Canvas & Floating UI (Days 8–10)

* [ ] Remove `@xyflow/react`; install `echarts`, `echarts-for-react`, and `framer-motion`.


* [ ] Build `FloatingSearchBar.tsx` and `SettingsGearPanel.tsx`.


* [ ] Implement `EChartsGraphCanvas.tsx` with custom card nodes and force layout.


* [ ] Build `SourceTraceDrawer.tsx` side panel (desktop) and mobile bottom sheet.


* [ ] **Validation:** Verify canvas purges stale nodes immediately when sliders or queries change.



#### Phase 5: End-to-End System Integration (Days 11–12)

* [ ] Execute E2E integration test suite (`tests/e2e/test_ui_provenance_pipeline.py`).


* [ ] Verify complete pipeline flow: News Agent $\rightarrow$ 9-Stage Harness $\rightarrow$ Kafka `raw-feed` $\rightarrow$ Zero-Mem Processor $\rightarrow$ ECharts WebGL Canvas.


* [ ] Confirm no UUIDs or database keys are displayed on the UI—only human-readable entity labels and original source text snippets.



---

## Key Verification & Validation Criteria

| Component | Target Metric / Assertion | Verification Command |
| --- | --- | --- |
| **Aggregator Governance** | 100% of agent calls pass through 9-stage Harness | <br>`go test ./pkg/harness/...`

 |
| **Ingestion Token Cost** | Strictly **0 Memory LLM Tokens** during stream indexing | <br>`pytest tests/test_zeromem_extractor.py`

 |
| **Retrieval Latency** | Multi-hop graph expansion ($D=2$) completes in $< 120\text{ms}$ | <br>`pytest tests/test_multi_hop_retrieval.py`

 |
| **Canvas State Freshness** | Stale nodes purged instantly upon query/setting change | <br>`npm run test:e2e` (Cypress/Playwright)

 |
| **Provenance Integrity** | Every node click opens unmodified source snippet with timestamp | E2E Audit (`test_ui_provenance_pipeline.py`)

 |
