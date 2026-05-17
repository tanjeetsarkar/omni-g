# Omni-G Tech Stack

A complete reference of every technology, library, and tool used across the Omni-G platform.

---

## 1. Container Runtime

| Technology | Version | Role |
|-----------|---------|------|
| **Docker Engine** | 29.5.0 | Container runtime (not Docker Desktop) |
| **Docker Compose** | v2 plugin | Multi-service orchestration with profiles (`core`, `vector`, `ai`, `observability`) |

---

## 2. Languages & Runtimes

| Language | Version | Used In | Notes |
|----------|---------|---------|-------|
| **Python** | 3.13 | Processor, GraphRAG service, MCP plugins | Managed via `uv` |
| **Go** | 1.26.3 | Aggregator | High-concurrency Kafka ingestion engine |
| **Node.js** | 24 LTS | Delivery frontend, WebSocket gateway | Managed via `nvm` |
| **TypeScript** | (bundled with Next.js) | Delivery frontend | Strict mode |

### Package Managers

| Tool | Version | Scope |
|------|---------|-------|
| **uv** | 0.11.14 | Python dependency management and tooling |
| **pnpm** | 11.x | Node.js package management (via Corepack) |
| **Go modules** | built-in | Go dependency management |

---

## 3. Infrastructure Services

### 3.1 Message Streaming

| Technology | Version / Image | Role |
|-----------|----------------|------|
| **Apache Kafka** | `apache/kafka:4.2.0` | Central nervous system — all raw events flow through Kafka topics. KRaft mode (no ZooKeeper). |
| **Redpanda Console** | `docker.redpanda.com/redpandadata/console` | Kafka UI (off by default on 8 GB RAM) |

**Core Kafka Topics:**

| Topic | Purpose |
|-------|---------|
| `raw-feed` | Raw ingested events from MCP plugins |
| `processed-entities` | Extracted STIX entities from the Processor |
| `analyst-alerts` | High-priority alerts pushed to the Delivery layer |

### 3.2 Graph Database

| Technology | Version / Image | Role |
|-----------|----------------|------|
| **Neo4j Community** | `neo4j:5.26.26-community` | Knowledge Graph store — nodes (Person, Org, Malware), edges (ATTRIBUTED_TO, TARGETS, USES) |
| **APOC** | (plugin) | Stored procedures for Neo4j |

> **Alternative:** `falkordb/falkordb:latest` — Redis-based graph DB, lower latency for high-throughput writes.

**Query Language:** Cypher
**Web UI:** Neo4j Browser at `http://localhost:7474`

### 3.3 Cache & Deduplication

| Technology | Version / Image | Role |
|-----------|----------------|------|
| **Redis Stack** | `redis/redis-stack:7.4.0-v8` | SHA-256 content deduplication, entity blocking cache, sliding-window botnet dedup |
| **RedisJSON** | (bundled) | JSON document storage |
| **RediSearch** | (bundled) | Full-text search for entity blocking queries |

**Web UI:** RedisInsight at `http://localhost:8001`

### 3.4 Vector Database

| Technology | Version / Image | Role |
|-----------|----------------|------|
| **Qdrant** | `qdrant/qdrant:v1.18.0` | Entity embeddings for semantic entity resolution (e.g. "Robert Smith" ≈ "Bob Smith") |

**Web UI:** Built-in dashboard at `http://localhost:6333/dashboard`

### 3.5 Object Storage

| Technology | Version / Image | Role |
|-----------|----------------|------|
| **MinIO** | `minio/minio:RELEASE.2025-09-07T16-13-09Z` | S3-compatible local storage for audio briefings, raw document archives, plugin artifact cache |

**Web UI:** MinIO Console at `http://localhost:9001`

---

## 4. Observability Stack

| Tool | Image | Purpose |
|------|-------|---------|
| **Prometheus** | `prom/prometheus:v3.11.3` | Metrics scraping from all services |
| **Grafana** | `grafana/grafana:13.0.1-security-01` | Dashboards — Kafka lag, graph write rate, LLM latency |
| **Loki** | `grafana/loki:3.7.2` | Log aggregation (structured JSON logs from all services) |

> Optional on 8 GB hardware — enable only when actively debugging metrics or logs.

---

## 5. AI / LLM Stack

### 5.1 Local LLM Runtime

| Tool | Role |
|------|------|
| **Ollama** | Model lifecycle manager, serves OpenAI-compatible API at `http://localhost:11434` |

**Models:**

| Model | Size | Purpose |
|-------|------|---------|
| `qwen2.5:3b` | ~2 GB | Primary local entity extraction model |
| `qwen2.5:1.5b` | ~1 GB | Low-memory fallback |
| `nomic-embed-text` | ~274 MB | Embedding model for vector entity blocking |

### 5.2 Text-to-Speech

| Tool | Image | Role |
|------|-------|------|
| **Kokoro TTS** | `ghcr.io/remsky/kokoro-fastapi-cpu:v0.2.2` | Audio briefing generation, OpenAI-compatible `/v1/audio/speech` endpoint |

> **Alternative:** Coqui TTS (`ghcr.io/coqui-ai/TTS`)

---

## 6. Python Dependencies

### 6.1 Processor Service

| Package | Version | Purpose |
|---------|---------|---------|
| `fastapi` | 0.115.6 | HTTP API framework |
| `pydantic` | 2.10.3 | Data validation and settings |
| `pydantic-settings` | 2.6.1 | Config from environment variables |
| `kafka-python-ng` | 2.2.3 | Kafka producer/consumer client |
| `redis[hiredis]` | 5.2.1 | Redis client with C-accelerated parser |
| `neo4j` | 5.27.0 | Neo4j driver |
| `qdrant-client` | 1.12.1 | Qdrant vector DB client |
| `langchain` | 0.3.10 | LLM orchestration framework |
| `langgraph` | 0.2.56 | Stateful LLM agent graphs |
| `instructor` | 1.7.0 | Structured LLM output extraction |
| `openai` | 1.57.2 | OpenAI-compatible API client (used against Ollama) |
| `sentence-transformers` | 3.3.1 | Local embedding generation |
| `stix2` | 3.0.1 | STIX 2.x threat intelligence object serialization |

### 6.2 MCP Plugin SDK

| Package | Version | Purpose |
|---------|---------|---------|
| `mcp` | 1.0.0 | Model Context Protocol SDK |
| `httpx` | 0.28.1 | Async HTTP client |
| `pydantic` | 2.10.3 | Data validation |

---

## 7. Go Dependencies (Aggregator)

| Module | Version | Purpose |
|--------|---------|---------|
| `confluent-kafka-go/v2` | v2.6.1 | High-performance Kafka client (requires `librdkafka-dev`) |
| `go-playground/validator/v10` | v10.23.0 | Struct validation |
| `google/uuid` | v1.6.0 | UUID generation for event IDs |
| `rs/zerolog` | v1.33.0 | Structured JSON logging |
| `spf13/viper` | v1.19.0 | Configuration management |

---

## 8. Frontend Dependencies (Delivery Layer)

### 8.1 Framework & Core

| Package | Version | Purpose |
|---------|---------|---------|
| `next` | 15.0.4 | React framework with App Router |
| `typescript` | (bundled) | Type safety |
| `tailwindcss` | (bundled) | Utility-first CSS |

### 8.2 Graph Visualization

| Package | Version | Purpose |
|---------|---------|---------|
| `sigma` | 3.0.1 | WebGL-accelerated graph rendering |
| `graphology` | 0.25.4 | In-memory graph data structure |
| `graphology-layout-forceatlas2` | 0.10.1 | Force-directed graph layout algorithm |
| `@nivo/network` | 0.88.0 | Network graph charts (D3-based) |

### 8.3 Real-Time & UI

| Package | Version | Purpose |
|---------|---------|---------|
| `socket.io-client` | 4.8.1 | WebSocket client (Kafka → browser) |
| `lucide-react` | 0.468.0 | Icon library |
| `clsx` | 2.1.1 | Conditional className utility |
| `tailwind-merge` | 2.5.5 | Tailwind class merging |
| `@radix-ui/*` | latest | Headless accessible UI primitives (add only components used) |

---

## 9. Data Standards

| Standard | Library | Purpose |
|----------|---------|---------|
| **STIX 2.x** | `stix2==3.0.1` | Structured Threat Information eXpression — canonical format for cyber threat entities and relationships |

---

## 10. Security & Sandboxing

| Tool | Role |
|------|------|
| **gVisor (`runsc`)** | Kernel-level sandbox for untrusted MCP plugin containers (Phase 2+). Registered as a Docker runtime. |
| **Docker network isolation** | `--network=none` + allow-list rules for Phase 1 local dev |

---

## 11. Development Tooling

| Tool | Version | Purpose | Install |
|------|---------|---------|---------|
| **VS Code** | — | IDE | pre-installed |
| **Bruno** | latest | API client (open-source Postman alternative) | `snap install bruno` |
| **k9s** | latest | Terminal Kubernetes UI (K8s phase) | `snap install k9s` |
| **ctop** | latest | Container resource monitor | `sudo apt install ctop` |
| **pre-commit** | 4.0.1 | Git hooks for linting/formatting | `uv tool install pre-commit==4.0.1` |
| **golangci-lint** | latest | Go linter | see [install docs](https://golangci-lint.run/usage/install/) |
| **ruff** | 0.8.2 | Python linter + formatter (Rust-based) | `uv tool install ruff==0.8.2` |

---

## 12. Architecture Summary

```
MCP Plugins (Python)
      │ HTTP/MCP
      ▼
Aggregator (Go) ──────► Kafka (raw-feed) ──────► Processor (Python)
                                                       │
                              ┌────────────────────────┤
                              │                        │
                           Neo4j                    Qdrant
                         (Knowledge                (Entity
                           Graph)                Embeddings)
                              │
                              ▼
                     GraphRAG Service (Python)
                              │
                    ┌─────────┴──────────┐
                    │                    │
              Kafka (analyst-alerts)   MinIO (audio)
                    │                    │
                    ▼                    ▼
            WebSocket Gateway      Kokoro TTS
                    │
                    ▼
           Next.js UI (Sigma.js)
```

**Cross-cutting concerns:**
- Redis — deduplication and caching at every ingest stage
- Prometheus + Grafana + Loki — observability across all services
- STIX 2.x — canonical data format throughout the pipeline
- OpenAI-compatible API contract — Processor talks to Ollama locally; swap to any cloud LLM without code changes
