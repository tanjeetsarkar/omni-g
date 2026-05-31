# Infrastructure

This directory contains all Docker Compose configuration, monitoring configs, and infrastructure-as-code for Omni-G.

## Directory Structure

```
infrastructure/
├── docker-compose.yml      # Main compose file with multi-profile setup
├── prometheus.yml          # Prometheus scrape configuration
├── loki-config.yml         # Loki log aggregation configuration
└── k8s/                    # Kubernetes manifests (Phase 5+)
```

---

## Docker Compose Profiles

Omni-G uses **Docker Compose profiles** to let you start only the services you need. This is critical on machines with limited RAM (8 GB target).

| Profile | Services | Approx RAM | Use When |
|---------|----------|------------|----------|
| `core` | Kafka, Redis, Neo4j | ~2.5 GB | Backend development, pipeline testing |
| `kafka-ui` | Redpanda Console | ~256 MB | Visual topic/message inspection and Kafka admin |
| `vector` | Qdrant | ~512 MB | Entity resolution development |
| `ai` | Ollama, Kokoro TTS | ~3 GB (+ model weights) | LLM extraction, audio briefings |
| `observability` | Prometheus, Grafana, Loki | ~512 MB | Monitoring and dashboards |
| `storage` | MinIO | ~256 MB | Audio file storage, exports |
| `services` | Aggregator, Processor, Delivery | ~512 MB | Running built application services |
| `all` | Everything | ~7 GB | Full integration testing |

### Starting Profiles

```bash
# Start only core infrastructure (recommended to start)
docker compose --env-file .env.docker.local --profile core up -d

# Add vector store
docker compose --env-file .env.docker.local --profile core --profile vector up -d

# Add Kafka UI (Redpanda Console)
docker compose --env-file .env.docker.local --profile core --profile kafka-ui up -d

# Add LLM services (heavy — downloads model weights on first run)
docker compose --env-file .env.docker.local --profile core --profile vector --profile ai up -d

# Add observability
docker compose --env-file .env.docker.local --profile core --profile observability up -d

# Full stack (Phase 3+ — requires all services to be built first)
docker compose --env-file .env.docker.local --profile all up -d
```

### Stopping

```bash
# Stop all running containers (preserves volumes)
docker compose down

# Stop and remove volumes (destructive — loses all data)
docker compose down -v
```

---

## Profile-Specific Setup

### `core` — Kafka, Redis, Neo4j

**Kafka** runs in KRaft mode (no ZooKeeper) on port `9092`.

```bash
# Verify Kafka is healthy
docker exec omni-g-kafka kafka-broker-api-versions.sh --bootstrap-server=localhost:9092

# List topics
docker exec omni-g-kafka kafka-topics.sh --bootstrap-server=localhost:9092 --list

# Create required topics manually (auto-created in dev, explicit in prod)
docker exec omni-g-kafka kafka-topics.sh --bootstrap-server=localhost:9092 \
  --create --topic raw-feed --partitions 6 --replication-factor 1
docker exec omni-g-kafka kafka-topics.sh --bootstrap-server=localhost:9092 \
  --create --topic analyst-alerts --partitions 3 --replication-factor 1
docker exec omni-g-kafka kafka-topics.sh --bootstrap-server=localhost:9092 \
  --create --topic dead-letter-queue --partitions 1 --replication-factor 1
```

### `kafka-ui` — Redpanda Console

Redpanda Console provides a browser UI for Kafka topics, partitions, consumer groups, and message browsing.

- UI URL: http://localhost:8088
- Backing broker: `kafka:9092` (inside Docker network)

```bash
# Start Kafka + Redpanda Console
docker compose --env-file .env.docker.local --profile core --profile kafka-ui up -d

# Verify UI health endpoint
curl http://localhost:8088/admin/health
```

**Redis** runs with [Redis Stack](https://redis.io/docs/stack/) (includes RediSearch and RedisJSON) on port `6379`. RedisInsight UI is available on port `8001`.

```bash
# Verify Redis
docker exec omni-g-redis redis-cli ping   # → PONG
```

**Neo4j** Community Edition runs on ports `7474` (HTTP browser) and `7687` (Bolt). APOC plugin is pre-loaded.

- Browser UI: http://localhost:7474
- Default credentials: `neo4j` / value of `NEO4J_PASSWORD` in `.env.docker.local`

```bash
# Verify Neo4j
docker exec omni-g-neo4j cypher-shell -u neo4j -p "$NEO4J_PASSWORD" "RETURN 1"
```

---

### `vector` — Qdrant

Qdrant vector database on port `6333` (HTTP) and `6334` (gRPC).

- REST API: http://localhost:6333
- Dashboard: http://localhost:6333/dashboard

```bash
# Verify Qdrant
curl http://localhost:6333/health
```

---

### `ai` — Ollama + Kokoro TTS

**Ollama** serves local LLMs on port `11434`. **Models are not pre-pulled** — pull them manually after the container starts:

```bash
# Pull required models (first run only — ~2–4 GB download)
docker exec omni-g-ollama ollama pull qwen2.5:3b
docker exec omni-g-ollama ollama pull nomic-embed-text

# Verify
curl http://localhost:11434/api/tags
```

**Kokoro TTS** serves a FastAPI text-to-speech endpoint on port `8000`.

```bash
curl http://localhost:8000/health
```

---

### `observability` — Prometheus, Grafana, Loki

| Service | URL | Credentials |
|---------|-----|-------------|
| Prometheus | http://localhost:9090 | None |
| Grafana | http://localhost:3000 | `admin` / `GF_SECURITY_ADMIN_PASSWORD` |
| Loki | http://localhost:3100 | None |

To add Loki as a Grafana data source: Grafana → Connections → Add Loki → URL: `http://loki:3100`.

---

### `storage` — MinIO

MinIO S3-compatible storage on port `9000` (API) and `9001` (Console UI).

- Console: http://localhost:9001
- Credentials: `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` from `.env.docker.local`

---

### `services` — Application Services

The `services` profile starts the built application containers (Aggregator, Processor, Delivery). These require **pre-built Docker images**. Build them first:

```bash
# Build all service images
docker compose build aggregator processor delivery

# Then start with dependencies
docker compose --env-file .env.docker.local --profile core --profile services up -d
```

---

## Health Checks

All services define health checks. Check overall health:

```bash
docker compose ps
# Look for "(healthy)" status on each container
```

Wait for all core services to become healthy before starting application services:

```bash
# Poll until healthy
until docker inspect omni-g-kafka --format '{{.State.Health.Status}}' | grep -q healthy; do
  echo "Waiting for Kafka..."; sleep 3;
done
```

---

## Resource Constraints

Omni-G is tuned for an **8 GB RAM development machine**:

| Service | Memory Limit | Notes |
|---------|-------------|-------|
| Neo4j | 2.5 GB (heap 2G + pagecache 512M) | Tune down if needed |
| Ollama | ~2–3 GB | Depends on model loaded |
| Kafka + ZooKeeper | ~512 MB | KRaft mode, no ZooKeeper |
| Redis Stack | ~256 MB | RediSearch indexes add overhead |
| Qdrant | ~256 MB | Grows with vector index size |
| Observability stack | ~512 MB | Prometheus + Grafana + Loki |

**Tip:** Start with `core` only during early development. Only add `ai` when working on LLM extraction.

---

## Environment Variables

Use split env files:
- [`.env.docker.example`](../.env.docker.example) -> copy to `.env.docker.local` for Docker Compose
- [`.env.services.example`](../.env.services.example) -> copy to `.env.services.local` for host-local service runs

```bash
cp .env.docker.example .env.docker.local
cp .env.services.example .env.services.local
# Edit local files with your values
```

**Never commit `.env.docker.local` or `.env.services.local` — both contain secrets and are gitignored.**
