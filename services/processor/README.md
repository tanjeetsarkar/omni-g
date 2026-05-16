# Processor Service

The **Processor** is the intelligence core of Omni-G. It consumes raw events from the `raw-feed` Kafka topic, extracts STIX 2.1 entities using an LLM, resolves entities against the existing knowledge graph, and persists results to Neo4j.

## Responsibilities

- **Kafka Consumer** — reads from `raw-feed` topic with consumer group support and DLQ handling
- **LLM Entity Extraction** — uses Ollama (via `instructor`) to extract STIX 2.1 entities from raw text
- **Redis Deduplication** — SHA-256 content hashing with 24-hour sliding TTL (Phase M3.2)
- **Entity Resolution** — vector + structural matching against existing graph nodes (Phase M4.1)
- **Neo4j Persistence** — writes STIX-compliant nodes and edges (Phase M4.2)
- **GraphRAG Indexing** — community detection and summary generation (Phase M4.3)
- **Validation Sidecar** — provides `/validate` endpoint for the Aggregator

## Directory Structure

```
processor/
├── src/
│   ├── processor/
│   │   ├── __init__.py
│   │   ├── main.py          # FastAPI app factory
│   │   └── config.py        # Pydantic-settings config
│   ├── models/
│   │   ├── __init__.py
│   │   └── stix.py          # STIX 2.1 Pydantic models
│   ├── llm/
│   │   ├── __init__.py
│   │   └── extractor.py     # LLM extraction skeleton
│   └── kafka/
│       ├── __init__.py
│       └── consumer.py      # Kafka consumer skeleton
├── tests/
│   ├── conftest.py          # pytest fixtures
│   ├── test_health.py
│   ├── test_models.py
│   └── test_extractor.py
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

| Method | Path        | Description                          |
|--------|-------------|--------------------------------------|
| `GET`  | `/health`   | Liveness probe                       |
| `GET`  | `/ready`    | Readiness probe                      |
| `POST` | `/validate` | Schema validation sidecar (M3.1)     |

## Docker

```bash
docker build -t omni-g/processor .
docker run -e KAFKA_BROKERS=kafka:9092 -p 8001:8001 omni-g/processor
```
