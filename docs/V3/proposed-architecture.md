# Proposed Architecture: Omni-G + Zero-Mem Integration

## Architectural Vision

Transition Omni-G’s memory, indexing, and retrieval mechanics from LLM-reliant GraphRAG operations to a **Zero-Token Memory Paradigm (Zero-Mem)**.

Zero-Mem handles generalized entity extraction, entity-context link formation, multi-hop sub-entity exploration, temporal hierarchy construction, and evidence calibration **100% non-generatively**. LLM calls are reserved solely for final synthesis in the **Delivery / Synthesis Stage**.

---

## Target Component Architecture

```
                  ┌────────────────────────────────────────┐
                  │          Aggregator Service            │
                  │  (Go / MCP Hosts / Event Standardizer) │
                  └──────────────────┬─────────────────────┘
                                     │ Kafka: raw-feed
                                     ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                      Processor Service (Python / FastAPI)                │
│                                                                          │
│ ┌──────────────────────┐  ┌────────────────────┐  ┌────────────────────┐ │
│ │ Redis Cache & De-dup │  │ Generalized NER    │  │ BGE-M3 Dense/BM25  │ │
│ └──────────┬───────────┘  └─────────┬──────────┘  └─────────┬──────────┘ │
│            │                        │                       │            │
│            ▼                        ▼                       ▼            │
│ ┌──────────────────────┐  ┌────────────────────┐  ┌────────────────────┐ │
│ │  Neo4j Database      │  │ Temporal Hierarchy │  │ Qdrant Vector DB   │ │
│ │ (Generalized Entity  │  │ Buckets            │  │ (Dense Embeddings) │ │
│ │ -Context Graph)      │  │                    │  │                    │ │
│ └──────────┬───────────┘  └─────────┬──────────┘  └─────────┬──────────┘ │
│            │                        │                       │            │
│            └───────────────────┐    │    ┌──────────────────┘            │
│                                ▼    ▼    ▼                               │
│                    ┌───────────────────────────────┐                     │
│                    │ Dual-View Retrieval Engine    │                     │
│                    │  - Relational Multi-Hop (PPR) │                     │
│                    │  - Hierarchical Depth Router  │                     │
│                    └───────────────┬───────────────┘                     │
│                                    │                                     │
│                                    ▼                                     │
│                    ┌───────────────────────────────┐                     │
│                    │ Bounded Evidence Calibration  │                     │
│                    │ (Depth & Token Window Limits) │                     │
│                    └───────────────┬───────────────┘                     │
└────────────────────────────────────┼─────────────────────────────────────┘
                                     │ Validated Context Array R(q)
                                     ▼
                  ┌────────────────────────────────────────┐
                  │    Delivery Service / LLM Reader       │
                  │    (Final Reader Call & UI Delivery)   │
                  └────────────────────────────────────────┘

```

---

## Core System Modifications

### 1. Ingestion Pipeline (`services/processor`)

* **Deprecate:** LLM-driven schema parsing, domain-specific STIX validators, and standard community summary generation.
* **Adopt:** Generalized NER models (spaCy / GLiNER) configured for generic entity types (`ORGANIZATION`, `PERSON`, `LOCATION`, `CONCEPT`, `STUDY`, `FACILITY`, etc.) to extract entities ($V_e$) and attach them directly to raw context units ($V_d$).
* **Storage Layer Updates:**
* **Neo4j:** Stores flexible, domain-agnostic nodes and edges:
* Nodes: `:ContextUnit` ($V_d$), `:Entity` ($V_e$)
* Edges: `:CO_OCCURRED_IN` ($E_{de}$), `:NEXT_CONTEXT` ($E_{dd}$)


* **Qdrant:** Stores dense embeddings ($\text{BGE-M3}$) for all context units $V_d$.
* **Postgres/Redis:** Stores multiscale temporal buckets ($U_{\text{turn}} \rightarrow U_{\text{window}} \rightarrow U_{\text{episode}}$).



### 2. Multi-Hop Depth Retrieval Engine

Routes user queries and recursively expands context based on semantic anchors (e.g., `Cancer Hospitals` $\rightarrow$ `Hospitals` $\rightarrow$ `Doctors` $\rightarrow$ `Clinical Trials/Studies`):

* **Relational Multi-Hop Expansion:** Executes **Personalized PageRank (PPR)** over $G = (V_d \cup V_e, E_{de} \cup E_{dd})$ initialized from matched anchor entities $V_{e,q}$, walking $k$-hops deep along entity-context connections.
* **Temporal Hierarchical Route:** Searches across coarse-to-fine time windows for localized event chains.
* **Score Fusion & Expansion Control:** Integrates PPR activation with dense vector similarity, maintaining a configurable maximum traversal depth $D_{\max}$ and token length budget $L_{\max}$.

### 3. Bounded Evidence Calibration

Prunes and orders retrieved context chains before handing them off to the reader LLM:

* Enforces hard context length caps ($L_{\max}$).
* Truncates entity expansion graphs beyond specified hop depths ($D_{\max}$).
* Deduplicates overlapping context spans across multi-hop traces.

---

## Key Challenges & Technical Resolutions

| Challenge | Impact | Resolution Path |
| --- | --- | --- |
| **PPR Latency in Large Neo4j Graphs** | Slower response times as the graph scales beyond $10^6$ nodes. | Implement **Local PPR approximation** using localized graph sub-traversals via Cypher/APOC, restricted to $k$-hop neighborhoods around anchor entities. |
| **Combinatorial Explosion during Multi-Hop Drills** | Querying broad entities (e.g., "Cancer Hospitals") can yield thousands of connected sub-entities (doctors, papers, locations). | Enforce **top-$k$ branch pruning** at each expansion hop using edge co-occurrence frequency and dense relevance scores. |
| **Noise in Co-occurrence Graphs** | Unrelated entities in the same document create clutter. | Apply tf-idf style edge-weighting on $E_{de}$: $w(d, e) = \frac{\text{freq}(e, d)}{\log(\text{degree}(e) + 1)}$. Prune edges below threshold $\tau$. |
| **Unbounded Query Length** | Context payload exceeds reader LLM context window. | Apply deterministic context fitting in the Calibration Engine, cutting off expansion once $L_{\max}$ token threshold is reached. |

---
