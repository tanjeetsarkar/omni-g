# System-Wide UI/UX & Backend Integration Roadmap

This document outlines the step-by-step technical implementation plan to support the **Figma-style Canvas, Custom Rich Nodes, and Guaranteed Provenance Engine** across **Delivery**, **Processor**, and **Aggregator** services.

---

## Service Contracts & Data Flow Overview

```
┌────────────────┐          ┌────────────────┐          ┌────────────────┐
│   AGGREGATOR   │          │   PROCESSOR    │          │  DELIVERY / UI │
│   (Go Service) │          │(Python/FastAPI)│          │  (Next.js 15)  │
└───────┬────────┘          └───────┬────────┘          └───────┬────────┘
        │                           │                           │
        │ Enriches Raw Event        │ Preserves Provenance &    │ Consumes Rich Nodes
        │ with Ingest Metadata      │ Builds Zero-Mem Graph     │ & Provenance Array
        │ (Source URL, Plugin ID)   │                           │
        │                           │                           │
        ├── RawEvent Envelope ─────►│                           │
        │   (Kafka: raw-feed)       │                           │
        │                           ├── Graph Response Payload ─►
        │                           │   (/api/v1/query)         │

```

---

## 1. Aggregator Service Updates (`services/aggregator`)

### Core Objective

Ensure that every payload ingested from MCP plugins or external feeds carries mandatory human-readable provenance metadata (source name, human-centric title, timestamp, source URL, and plugin identity).

### Code Base Changes

#### A. Envelope Contract Enrichment (`pkg/models/event.go`)

Extend the `RawEvent` envelope struct to enforce human-readable source metadata fields.

```go
type RawEvent struct {
    ID             string                 `json:"id"`
    [cite_start]TenantID       string                 `json:"tenant_id"`       // Multi-tenancy [cite: 340]
    [cite_start]Source         string                 `json:"source"`          // Source identifier / URL [cite: 337]
    SourceName     string                 `json:"source_name"`     // e.g. "PubMed Central", "ClinicalTrials.gov"
    SourceURL      string                 `json:"source_url,omitempty"`
    [cite_start]Timestamp      time.Time              `json:"timestamp"`       // Ingestion timestamp [cite: 338]
    PluginName     string                 `json:"plugin_name"`     // e.g. [cite_start]"mcp-health-scraper" [cite: 339]
    [cite_start]PluginVersion  string                 `json:"plugin_version"`  // [cite: 339]
    [cite_start]Payload        map[string]interface{} `json:"payload"`         // Original content [cite: 338]
    [cite_start]SchemaVersion  string                 `json:"schema_version"`  // [cite: 340]
}

```

#### B. Ingestion Normalizer (`internal/ingest/normalizer.go`)

* Update the MCP tool response parser (`tools/call`) to extract human-centric labels (e.g., `document_title`, `publisher_name`) from incoming content blocks.


* Default `SourceName` to `PluginName` if `source_name` is absent in raw MCP outputs.



### Validation Criteria

* **Unit Test:** `go test ./pkg/models/...`
* Assert that marshalling `RawEvent` without `source_name` or `timestamp` fails validation.


*
**Integration Test:** Ingest a sample MCP feed item and verify that published Kafka messages on `raw-feed` contain valid `source_name` and `plugin_name` fields.



---

## 2. Processor Service Updates (`services/processor`)

### Core Objective

Eliminate legacy STIX validations, persist complete provenance metadata inside Neo4j `:ContextUnit` and `:Entity` nodes, and expose clean, non-stale multi-hop graph endpoints.

### Code Base Changes

#### A. Database Schema & Graph Indexer (`src/indexers/graph_indexer.py`)

* Update Neo4j Cypher persistence scripts to store human-readable metadata directly on `:ContextUnit` ($V_d$) and `:Entity` ($V_e$) nodes:



```cypher
// Persist Context Unit with Source Metadata
MERGE (d:ContextUnit {id: $context_id})
SET d.text = $raw_text,
    d.source_id = $source_id,
    d.source_name = $source_name,
    d.source_url = $source_url,
    d.plugin_name = $plugin_name,
    d.created_at = $timestamp,
    d.char_offset_start = $start_offset,
    d.char_offset_end = $end_offset;

// Persist Generalized Entity
MERGE (e:Entity {name: $entity_name})
ON CREATE SET e.type = $entity_type,
              e.created_at = $timestamp;

// Persist Co-occurrence Edge
MERGE (e)-[r:CO_OCCURRED_IN]->(d)
SET r.weight = $co_occurrence_weight,
    r.updated_at = $timestamp;

```

#### B. PageRank & Multi-Hop Query Engine (`src/retrieval/ppr_engine.py`)

Update localized Personalized PageRank (PPR) query response formatting to return rich node attributes and strict evidence provenance arrays:

```python
class NodeProvenance(BaseModel):
    source_name: str
    source_url: Optional[str] = None
    ingested_at: str
    mcp_plugin_name: str

class RawContextSnippet(BaseModel):
    snippet_text: str
    char_offset_start: int
    char_offset_end: int
    document_id: str

class CustomNodeResponse(BaseModel):
    id: str
    entity_name: str
    entity_type: str
    sub_entity_count: int
    confidence_score: float
    source: NodeProvenance
    raw_context: RawContextSnippet

class GraphQueryResponse(BaseModel):
    nodes: List[CustomNodeResponse]
    links: List[dict]
    [cite_start]total_tokens_consumed: int = 0  # Zero-Mem verification [cite: 5, 42]

```

#### C. Invalidation & Freshness Layer (`src/api/routes/query.py`)

* Add dynamic query parameter support for `relevance_threshold` ($\tau$) and `traversal_depth` ($D_{\max}$).


* Hard-prune edges below threshold $\tau$ dynamically inside APOC PageRank traversals to ensure no stale or low-weight nodes reach the client.



### Validation Criteria

* **Unit Test:** `pytest tests/test_provenance_schema.py`
* Assert every entity node returned from `/api/v1/query` contains non-null `source_name` and `snippet_text`.


*
**Latency Benchmark:** Verify multi-hop retrieval ($D=2$) with top-$K$ branch pruning executes under $120\text{ms}$.



---

## 3. Delivery Service & Frontend Updates (`apps/web` & `services/delivery`)

### Core Objective

Implement the Figma-style floating canvas interface using Apache ECharts WebGL, custom rich text node formatting, and non-blocking evidence drawers.

### Code Base Changes

#### A. Dependency Cleanup (`apps/web/package.json`)

*
**Uninstall:** `@xyflow/react`, `reactflow`.


*
**Install:** `echarts`, `echarts-for-react`, `framer-motion` (for mobile drawers), `clsx`, `tailwind-merge`.



#### B. Global Canvas State Manager (`apps/web/src/store/useGraphExplorerStore.ts`)

Implement canvas state clearing upon search/setting updates to prevent rendering stale graphs:

```typescript
import { create } from 'zustand';

interface GraphState {
  query: string;
  depth: number;
  relevanceThreshold: number;
  nodes: CustomCanvasNode[];
  edges: CustomCanvasEdge[];
  selectedNode: CustomCanvasNode | null;
  isLoading: boolean;

  // Actions
  setQuery: (query: string) => void;
  setSettings: (depth: number, threshold: number) => void;
  executeQuery: () => Promise<void>;
  selectNode: (nodeId: string | null) => void;
  clearCanvas: () => void;
}

export const useGraphExplorerStore = create<GraphState>((set, get) => ({
  query: '',
  depth: 2,
  relevanceThreshold: 0.65,
  nodes: [],
  edges: [],
  selectedNode: null,
  isLoading: false,

  clearCanvas: () => set({ nodes: [], edges: [], selectedNode: null }),

  executeQuery: async () => {
    const { query, depth, relevanceThreshold, clearCanvas } = get();
    if (!query) return;

    // STEP 1: Purge stale canvas state immediately
    clearCanvas();
    set({ isLoading: true });

    try {
      const res = await fetch(`/api/v1/query`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query, depth, threshold: relevanceThreshold })
      });
      const data = await res.json();

      // STEP 2: Render fresh nodes
      set({ nodes: data.nodes, edges: data.links, isLoading: false });
    } catch (err) {
      set({ isLoading: false });
    }
  }
}));

```

#### C. Custom Rich Canvas Node Formatter (`apps/web/src/components/canvas/useEChartsGraphAdapter.ts`)

Transform API response nodes into formatted ECharts rich-text visual cards:

```typescript
export const convertToEChartsOptions = (nodes: any[], edges: any[], threshold: number) => {
  return {
    tooltip: { show: false }, // Using custom Floating Evidence Drawer instead
    series: [
      {
        type: 'graph',
        layout: 'force',
        animationDurationUpdate: 500,
        data: nodes.map((node) => ({
          id: node.id,
          name: node.entity_name,
          symbol: 'roundRect',
          symbolSize: [170, 54], // Card dimensions
          label: {
            show: true,
            position: 'inside',
            formatter: [
              `{typeBadge| ${node.entity_type} }`,
              `{title| ${node.entity_name} }`,
              `{subText| +${node.sub_entity_count} links } {source| 📍 ${node.source.source_name} }`
            ].join('\n'),
            rich: {
              typeBadge: { backgroundColor: '#2563EB', color: '#FFF', borderRadius: 3, padding: [2, 4], fontSize: 9 },
              title: { color: '#F8FAFC', fontSize: 12, fontWeight: 'bold', padding: [3, 0] },
              subText: { color: '#94A3B8', fontSize: 9 },
              source: { color: '#38BDF8', fontSize: 9 }
            }
          },
          itemStyle: {
            color: '#0F172A',
            borderColor: '#334155',
            borderWidth: 1.5,
            borderRadius: 8
          },
          provenancePayload: node
        })),
        edges: edges.filter(e => e.weight >= threshold).map(e => ({
          source: e.source,
          target: e.target,
          lineStyle: { width: Math.max(1, e.weight * 3), opacity: 0.7, color: '#475569' }
        })),
        force: {
          repulsion: 350,
          edgeLength: 120,
          gravity: 0.1
        }
      }
    ]
  };
};

```

#### D. Floating UX Components (Figma-Style UI)

1. **`FloatingSearchBar.tsx`**: Top-center frosted-glass search pill with responsive auto-complete and keyboard enter trigger (`Enter`).
2. **`SettingsGearPanel.tsx`**: Top-right gear icon popover containing dials for:
* Relevance Threshold Slider ($\tau \in [0.1, 1.0]$)


* Traversal Depth Dial ($D_{\max} \in [1, 4]$)


* Token Limit Cap ($L_{\max} \in [2048, 8192]$)




3.
**`SourceTraceDrawer.tsx`**: Slide-in side drawer (desktop) and swipeable Framer Motion bottom sheet (mobile) that opens on single-node click to display human-readable source attributes and original context traces.



---

## Implementation Timeline & Phase Roadmap

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ PHASE 1: Contract Enforcement & Aggregator Source Meta (Days 1–2)            │
├─────────────────────────────────────────────────────────────────────────────┤
│ PHASE 2: Processor Graph Indexer & Invalidation Engine (Days 3–4)           │
├─────────────────────────────────────────────────────────────────────────────┤
│ PHASE 3: Delivery Frontend Fullscreen ECharts & State Manager (Days 5–7)    │
├─────────────────────────────────────────────────────────────────────────────┤
│ PHASE 4: Responsive Floating Drawer & End-to-End Validation (Days 8–9)     │
└─────────────────────────────────────────────────────────────────────────────┘

```

### Phase 1: Ingestion & Aggregator Contract Normalization

* [ ] Enforce `source_name`, `source_url`, and `plugin_name` in Aggregator `RawEvent` schema.


* [ ] Update MCP ingestion pipeline to extract document titles and publishers.


* [ ] Write integration test verifying Kafka payload schema compliance.



### Phase 2: Processor Provenance Indexing & Fresh API

* [ ] Update Neo4j Cypher queries in `graph_indexer.py` to persist source provenance attributes on all nodes/edges.


* [ ] Refactor `/api/v1/query` endpoint to return structured custom node payloads and dynamically prune low-weight edges ($\tau$).


* [ ] Run benchmark testing to verify $0$ LLM memory token usage during graph expansion.



### Phase 3: Delivery Fullscreen Canvas & State Engine

* [ ] Uninstall `@xyflow/react` and install `echarts`, `echarts-for-react`, `framer-motion`.


* [ ] Create `useGraphExplorerStore.ts` with canvas state purging before executing new queries.
* [ ] Build `EChartsGraphCanvas.tsx` using `useEChartsGraphAdapter` rich-text card formatting.


* [ ] Implement `FloatingSearchBar.tsx` (top-center) and `SettingsGearPanel.tsx` (top-right).

### Phase 4: Responsive Mobile Drawer & Provenance Verification

* [ ] Implement `SourceTraceDrawer.tsx` as a side panel on desktop and bottom-sheet on mobile.


* [ ] Connect node click event handlers (`chart.on('click')`) to populate the provenance drawer.


* [ ] Execute E2E automated test suite (`tests/e2e/test_ui_provenance_pipeline.py`) validating:
1. Stale canvas state is purged upon query change.
2. Every rendered node displays a human-readable title and source tag.
3. Clicking a node opens source trace evidence with matching document snippets.
