# Delivery Service

The **Delivery** service is the real-time knowledge graph frontend for Omni-G. Users enter a search query; the system performs a semantic search against the vector database, fetches matched entities and their neighbors from Neo4j, and renders them as an interactive React Flow graph. New entities added by the Processor animate into the graph in real time.

## Responsibilities

- **Search-First Graph UI** — user query → Qdrant semantic search → React Flow graph of matched entities + neighbors
- **WebSocket Gateway** — standalone Node.js process that consumes `analyst-alerts` from Kafka and broadcasts new entity events to connected browsers
- **Inline Node Information** — every node displays entity type, name, confidence, and key properties; no sidebars or detail panels
- **Real-Time Graph Growth** — new connected entities animate into the existing layout; disconnected new entities appear as a floating incoming cluster
- **Audio Briefings** — GraphRAG-generated daily briefings via `/api/briefings` (deprioritized, available but not primary UX)

## UX Flow

```
User types query
      ↓
POST /api/search  { q: "...", tenant_id: "..." }
      ↓
Embed query → Qdrant semantic search → top-N entity IDs
      ↓
Fetch matched entities + 1–2 hop neighbors from Neo4j
      ↓
React Flow renders graph
  - Each node: entity type badge, name, confidence, key properties (inline)
  - Click node: expands inline to show all properties (no sidebar)
      ↓
WebSocket connection open
  - New entities connected to current graph → animate into layout (force re-simulation)
  - New disconnected entities → appear as floating incoming cluster at canvas edge
```

## Directory Structure

```
delivery/
├── src/
│   ├── app/
│   │   ├── layout.tsx                  # Root layout
│   │   ├── page.tsx                    # Search bar (entry point)
│   │   └── api/
│   │       ├── health/route.ts         # Liveness probe
│   │       ├── search/route.ts         # Semantic search → Neo4j neighbors
│   │       └── briefings/              # Audio briefing list + download (deprioritized)
│   ├── components/
│   │   └── graph/
│   │       ├── KnowledgeGraph.tsx      # React Flow canvas (root graph component)
│   │       ├── EntityNode.tsx          # Custom node: inline entity info + expandable properties
│   │       └── IncomingCluster.tsx     # Floating cluster for disconnected real-time nodes
│   ├── hooks/
│   │   ├── useGraphSearch.ts           # Drives /api/search and populates React Flow nodes/edges
│   │   └── useRealtimeNodes.ts         # Consumes WebSocket alerts, animates new nodes into layout
│   ├── lib/
│   │   ├── socket.ts                   # Socket.io client singleton
│   │   └── neo4j.ts                    # Neo4j driver singleton (server-side)
│   └── types/
│       └── graph.ts                    # Entity, Relationship, GraphNode, GraphEdge interfaces
├── gateway/
│   ├── server.ts                       # Standalone WebSocket/Kafka consumer (port 3001)
│   └── tsconfig.json
├── jest.config.ts
├── jest.setup.ts
├── next.config.ts
├── Dockerfile
└── README.md
```

## Key Design Decisions

### No Sidebars or Filter Panels

All entity information is displayed inside the node. Clicking a node expands its inline view to show additional properties. This keeps the canvas the primary interface.

### Search-Driven Entry — No Full Graph Load

The graph only renders entities relevant to the current search query plus their 1–2 hop neighbors. Loading the full graph is explicitly rejected (performance degrades with graph size; UX becomes unfocused).

### Real-Time Layout Strategy

- **Connected nodes:** When a new entity is linked to nodes already in the current view, it is added to the React Flow state and the force simulation is re-run on the affected subgraph neighborhood. This keeps the existing layout stable.
- **Disconnected nodes:** Entities not connected to the current view appear in a floating cluster at the canvas edge. Users can explore them independently or drag them into the main graph.

### Graph Visualization Library

React Flow (`@xyflow/react`) with `dagre` for initial hierarchical layout and force re-simulation for live updates. Custom node components handle inline entity rendering.

## Configuration

| Variable                    | Default                  | Description                              |
| --------------------------- | ------------------------ | ---------------------------------------- |
| `NEXT_PUBLIC_WS_URL`        | `ws://localhost:3001`    | WebSocket gateway URL                    |
| `NEXT_PUBLIC_PROCESSOR_URL` | `http://localhost:8001`  | Processor API base URL                   |
| `NEO4J_URL`                 | `neo4j://localhost:7687` | Neo4j bolt URL (server-side queries)     |
| `NEO4J_USER`                | `neo4j`                  | Neo4j username                           |
| `NEO4J_PASSWORD`            | `omni-g-password`        | Neo4j password                           |
| `QDRANT_URL`                | `http://localhost:6333`  | Qdrant vector DB URL (for `/api/search`) |
| `OLLAMA_URL`                | `http://localhost:11434` | Ollama URL for query embedding           |

## Running Locally

```bash
pnpm install
pnpm dev          # starts Next.js on :3000
pnpm test         # run Jest
pnpm build        # production build
```

To run the WebSocket gateway:

```bash
cd gateway
npx ts-node server.ts   # starts on :3001
```

## API Endpoints

| Method | Path                  | Description                                            |
| ------ | --------------------- | ------------------------------------------------------ |
| `GET`  | `/api/health`         | Liveness probe                                         |
| `POST` | `/api/search`         | Semantic search → entity IDs → Neo4j neighbors → graph |
| `GET`  | `/api/briefings`      | List daily audio briefings (deprioritized)             |
| `GET`  | `/api/briefings/[id]` | Presigned audio file download (deprioritized)          |

### `POST /api/search` Request/Response

```json
// Request
{ "q": "apple acquisition 2026", "tenant_id": "tenant-a" }

// Response
{
  "nodes": [
    {
      "id": "uuid",
      "type": "Organization",
      "name": "Apple Inc.",
      "confidence": 0.92,
      "properties": { "sector": "Technology" },
      "community_id": "c-42",
      "community_summary": "Tech sector M&A activity..."
    }
  ],
  "edges": [
    { "id": "uuid", "source": "uuid-a", "target": "uuid-b", "type": "ACQUIRED", "confidence": 0.88 }
  ]
}
```

## Docker

```bash
docker build -t omni-g/delivery .
docker run -p 3000:3000 omni-g/delivery
```

Check out our [Next.js deployment documentation](https://nextjs.org/docs/app/building-your-application/deploying) for more details.
