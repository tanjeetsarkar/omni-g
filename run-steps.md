# Omni-G Run Steps

## Prerequisites

### Ollama (LLM inference)

Ollama is **not** in docker-compose (commented out). The Processor requires it for STIX extraction.

```bash
# Install: https://ollama.com/download
ollama serve &
ollama pull qwen2.5:1.5b
```

Alternatively set `OPENAI_API_KEY` in your env file — the Processor falls back to the OpenAI-compatible API automatically.

---

## Path A — Full Docker Compose (recommended)

Everything runs in containers.

```bash
cd infrastructure

# 1. Build all service images
docker compose --env-file .env.docker.local build

# 2. Start infrastructure (Kafka, Neo4j, Redis, Qdrant) and wait until healthy
docker compose --env-file .env.docker.local --profile core up -d
docker compose --env-file .env.docker.local --profile core ps

# 3. Start application services + OSINT plugins
docker compose --env-file .env.docker.local --profile services up -d

# 4. Tail logs
docker compose --env-file .env.docker.local logs -f aggregator processor delivery
```

Open **http://localhost:3000** in your browser.

---

## Path B — Docker infra + host-run services

Infrastructure runs in Docker; Aggregator, Processor, and Delivery run on the host.

```bash
# Terminal 1 — infrastructure
cd infrastructure
docker compose --env-file .env.docker.local --profile core up -d

# Terminal 2 — OSINT MCP plugins (lightweight Go binaries, run in Docker)
cd infrastructure
docker compose --env-file .env.docker.local up -d \
  mcp-echo mcp-wikipedia mcp-wikidata mcp-newsrss mcp-reuters

# Load env for all host services (run once per shell session)
cd /path/to/omni-g
set -a && source .env.services.local && set +a

# Terminal 3 — Processor
cd services/processor
uv run uvicorn src.processor.main:app --host 0.0.0.0 --port 8001

# Terminal 4 — Aggregator
cd services/aggregator
go run ./cmd/aggregator

# Terminal 5 — Delivery (Next.js + WebSocket gateway)
cd services/delivery
pnpm dev
```

Open **http://localhost:3000** in your browser.

---

## Verify the stack is up

```bash
# Infrastructure
curl http://localhost:19092         # Kafka (TCP open for host-run services)
curl http://localhost:7474          # Neo4j Browser
curl http://localhost:6379          # Redis (PONG via redis-cli ping)

# Services
curl http://localhost:8080/health   # Aggregator
curl http://localhost:8001/health   # Processor
curl http://localhost:3000/api/health  # Delivery

# OSINT plugins
curl http://localhost:8090/health   # mcp-echo
curl http://localhost:8091/health   # mcp-wikipedia
curl http://localhost:8092/health   # mcp-wikidata
curl http://localhost:8093/health   # mcp-newsrss
curl http://localhost:8094/health   # mcp-reuters
```

---

## Run an E2E query

1. Open **http://localhost:3000**
2. Type `Sundar Pichai` in the search bar and press **Search**
3. Watch the pipeline progress stages animate (OSINT fetch → Kafka → AI extraction → Neo4j → GraphRAG)
4. When the WebSocket alert fires (or after 60 s fallback), click **View Knowledge Graph**
5. The dashboard opens pre-filtered for `Sundar Pichai` with live Neo4j data

---

## Tear down

```bash
# Stop everything (preserve volumes)
cd infrastructure
docker compose --env-file .env.docker.local --profile all down

# Stop and delete all volumes (full reset)
docker compose --env-file .env.docker.local --profile all down -v
```
