# Processor Service

The **Processor** is the intelligence core of Omni-G. It consumes raw events from the `raw-feed` Kafka topic, extracts generic open-ended entities using an LLM, resolves entities against the existing knowledge graph, and persists results to Neo4j.

## Responsibilities

- **Kafka Consumer** — reads from `raw-feed` topic with consumer group support and DLQ handling
- **LLM Entity Extraction** — uses Ollama (via `instructor`) to extract generic entities from raw text; the LLM determines the entity type freely (Person, Organization, Event, Location, Topic, Concept, etc.)
- **Redis Deduplication** — SHA-256 content hashing with 24-hour sliding TTL
- **Entity Resolution** — vector + structural matching against existing graph nodes (Qdrant semantic blocking + Neo4j structural, confidence tiers below)
- **Neo4j Persistence** — writes generic entity nodes and typed relationships
- **GraphRAG Indexing** — community detection and summary generation
- **Alert Publishing** — publishes high-confidence entities to `analyst-alerts` for real-time delivery
- **Validation Sidecar** — provides `/validate` endpoint for the Aggregator

## Entity & Relationship Models

### Entity

```python
class Entity(BaseModel):
    id: str                         # UUID
    type: str                       # Open-ended: determined by LLM (Person, Organization, Event, ...)
    name: str
    description: str | None = None
    properties: dict[str, Any] = {}  # Domain-specific attributes
    confidence: float               # 0.0–1.0
    tenant_id: str
    source_id: str
    created: datetime
    modified: datetime
```

### Relationship

```python
class Relationship(BaseModel):
    id: str                         # UUID
    type: str                       # Open-ended: KNOWS, LOCATED_AT, PARTICIPATED_IN, ACQUIRED, etc.
    source_id: str
    target_id: str
    confidence: float
    properties: dict[str, Any] = {}
```

### Entity Resolution Confidence Tiers

| Tier | Threshold | Action |
|------|-----------|--------|
| `AUTO_MERGE` | ≥ 0.95 | Merge automatically |
| `AMBIGUOUS` | 0.50 – 0.95 | Flag for review, merge tentatively |
| `NEW_ENTITY` | < 0.50 | Create new node |

## Neo4j Graph Schema

Nodes use the label pattern `:Entity:{TypeLabel}:{tenant_label}`.

```cypher
// Example node
(:Entity:Organization:tenant_a {
    id: "uuid",
    name: "Apple Inc.",
    type: "Organization",
    confidence: 0.92,
    source_id: "plugin-newsrss-v1",
    created: datetime(),
    modified: datetime()
})

// Example edge
-[:ACQUIRED { confidence: 0.88, id: "uuid" }]->
```

Indexes:

```cypher
CREATE INDEX entity_id FOR (e:Entity) ON (e.id);
CREATE INDEX entity_tenant FOR (e:Entity) ON (e.tenant_id);
CREATE INDEX entity_type FOR (e:Entity) ON (e.type);
```

## Processing Pipeline

1. **Consume** — read event from `raw-feed`
2. **Deduplicate** — SHA-256 hash check in Redis; skip if seen within 24h
3. **Extract** — LLM extracts entities and relationships (async with timeout to DLQ)
4. **Validate** — Pydantic validates entity and relationship schemas
5. **Resolve** — Qdrant semantic blocking finds candidate matches; Neo4j structural scoring confirms; apply confidence tier
6. **Persist** — write/merge nodes and edges in Neo4j under `tenant_id`
7. **GraphRAG** — periodically trigger community detection and summary refresh
8. **Alert** — publish high-confidence entities to `analyst-alerts` Kafka topic

## Directory Structure

```
processor/
├── src/
│   ├── processor/
│   │   ├── __init__.py
│   │   ├── main.py           # FastAPI app factory
│   │   └── config.py         # Pydantic-settings config
│   ├── models/
│   │   ├── __init__.py
│   │   └── entities.py       # Generic Entity + Relationship Pydantic models
│   ├── kafka/
│   │   ├── __init__.py
│   │   └── consumer.py       # Kafka consumer
│   ├── llm/
│   │   ├── __init__.py
│   │   └── extractor.py      # LLM entity extraction
│   ├── dedup/
│   │   ├── __init__.py
│   │   └── dedup.py          # Redis SHA-256 deduplication
│   ├── resolution/
│   │   ├── __init__.py
│   │   └── resolver.py       # Entity resolution (Qdrant + Neo4j)
│   ├── graph/
│   │   ├── __init__.py
│   │   └── graph.py          # Neo4j persistence
│   ├── graphrag/
│   │   ├── __init__.py
│   │   └── graphrag.py       # Community detection + summarization
│   └── briefing/
│       ├── __init__.py
│       ├── script_generator.py   # GraphRAG-driven briefing script
│       ├── tts_synthesizer.py    # Kokoro TTS
│       └── storage.py            # MinIO audio storage
├── tests/
├── pyproject.toml
├── Dockerfile
└── README.md
```

## Configuration

| Variable              | Default                    | Description                            |
|-----------------------|----------------------------|----------------------------------------|
| `LOG_LEVEL`           | `info`                     | Log level                              |
| `HTTP_PORT`           | `8001`                     | HTTP server port                       |
| `KAFKA_BROKERS`       | `localhost:9092`           | Kafka bootstrap servers                |
| `KAFKA_GROUP_ID`      | `processor-group`          | Consumer group ID                      |
| `REDIS_URL`           | `redis://localhost:6379`   | Redis connection URL                   |
| `NEO4J_URL`           | `neo4j://localhost:7687`   | Neo4j bolt URL                         |
| `NEO4J_USER`          | `neo4j`                    | Neo4j username                         |
| `NEO4J_PASSWORD`      | `omni-g-password`          | Neo4j password                         |
| `QDRANT_URL`          | `http://localhost:6333`    | Qdrant vector DB URL                   |
| `OLLAMA_URL`          | `http://localhost:11434`   | Ollama LLM server URL                  |
| `OLLAMA_MODEL`        | `qwen2.5:3b`               | Model for entity extraction            |
| `EMBEDDING_MODEL`     | `nomic-embed-text`         | Model for generating entity embeddings |

## Running Locally

```bash
# Install dependencies with uv
uv sync

# Run development server
uv run fastapi dev src/processor/main.py

# Run tests
uv run pytest

# Lint
uv run ruff check src/ tests/

# Type check
uv run mypy src/
```

## API Endpoints

| Method | Path              | Description                             |
|--------|-------------------|-----------------------------------------|
| `GET`  | `/health`         | Liveness probe                          |
| `GET`  | `/ready`          | Readiness probe                         |
| `POST` | `/validate`       | Schema validation sidecar               |
| `GET`  | `/briefings`      | List available audio briefings          |
| `GET`  | `/briefings/{id}` | Get presigned URL for briefing download |

## Docker

```bash
docker build -t omni-g/processor .
docker run -e KAFKA_BROKERS=kafka:9092 -p 8001:8001 omni-g/processor
```
