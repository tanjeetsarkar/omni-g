# Implementation Roadmap: Zero-Mem Integration

A step-by-step operational guide to integrating the Zero-Mem paradigm into Omni-G with generalized domain support.

---

## Phase 1: Zero-Token Ingestion Pipeline

**Goal:** Remove STIX validation and LLM dependency from event ingestion in `services/processor`.

* [ ] **Step 1.1: Integrate Generalized Extractor**
* Add `spacy` and `gliner` dependencies to `services/processor/pyproject.toml`.
* Create `services/processor/src/extractors/zeromem_extractor.py` to perform domain-agnostic entity detection (organizations, persons, locations, concepts, studies, etc.) without STIX constraints or LLM API calls.


* [ ] **Step 1.2: Refactor Neo4j Graph Schema**
* Update Neo4j Cypher scripts for generalized Entity-Context graph modeling:
* Nodes: `:ContextUnit` ($V_d$), `:Entity` ($V_e$)
* Edges: `:CO_OCCURRED_IN` ($E_{de}$), `:NEXT_CONTEXT` ($E_{dd}$)


* Purge STIX-specific entity schemas and relationship constraints.


* [ ] **Step 1.3: Embeddings & Vector Store Setup**
* Integrate `FlagEmbedding` (BGE-M3) into `services/processor/src/indexers/vector.py`.
* Configure Qdrant collection to index raw context units with payload references to Postgres/Neo4j `source_id`.


* [ ] **Step 1.4: Ingestion Pipeline Validation**
* Benchmark ingestion throughput on generalized text feeds.
* Confirm **0 token consumption** during Kafka stream ingestion.



---

## Phase 2: Multi-Hop Dual-View Retrieval System

**Goal:** Implement Personalized PageRank for multi-hop entity exploration (e.g., Hospital $\rightarrow$ Doctor $\rightarrow$ Study) and temporal search.

* [ ] **Step 2.1: Query Profiler & Anchor Matcher**
* Create `services/processor/src/retrieval/profiler.py` to extract generalized anchor entities and determine query depth targets.


* [ ] **Step 2.2: Multi-Hop Relational Search (PPR in Neo4j)**
* Implement APOC Personalized PageRank query in `services/processor/src/retrieval/relational.py`.
* Enable recursive graph walks to pull adjacent context units and connected sub-entities up to depth $D_{\max}$.


* [ ] **Step 2.3: Temporal Hierarchy Route**
* Create temporal bucket manager in Redis/Postgres (`services/processor/src/retrieval/temporal.py`).
* Implement coarse-to-fine temporal window traversal ($U_{\text{episode}} \rightarrow U_{\text{window}} \rightarrow U_{\text{turn}}$).


* [ ] **Step 2.4: Score Fusion Engine**
* Implement deterministic score fusion combining PPR relevance, BGE-M3 dense similarity, and graph hop distance.



---

## Phase 3: Evidence Calibration & Delivery Integration

**Goal:** Control evidence context length and feed structured drill-down data to the UI canvas.

* [ ] **Step 3.1: Bounded Evidence Calibrator**
* Build `services/processor/src/calibration/calibrator.py`.
* Implement top-$k$ branch pruning, context window fitting ($L_{\max}$ token limit), and span deduplication.


* [ ] **Step 3.2: Update Delivery Service Contracts**
* Update FastAPI response formats to return structured multi-hop evidence arrays $R(q)$ with source IDs and temporal breadcrumbs.
* Update `services/delivery` API connectors to pass calibrated evidence directly into the final LLM prompt payload.


* [ ] **Step 3.3: Frontend Canvas Alignment**
* Update Next.js graph canvas (Sigma.js) to display multi-level entity expansions (e.g., clicking/searching a hospital node visually expands connected doctor and study nodes).



---

## Phase 4: Benchmarking & Optimization

**Goal:** Validate performance, cost, and depth control.

* [ ] **Step 4.1: Multi-Hop Depth Verification**
* Run benchmark queries across varying depth settings ($D=1, 2, 3$) to verify branch pruning efficiency and context relevance.


* [ ] **Step 4.2: Latency & Cost Audit**
* Verify reduction in query response latency compared to traditional multi-stage LLM prompts.
* Confirm total memory-layer token consumption remains strictly at zero.
