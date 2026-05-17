# Omni-G: Local Development Prerequisites

This document outlines everything required to build and run the Omni-G platform locally using 100% open-source, containerized tooling. The recommendations below are tuned for an 8 GB RAM, 100 GB SSD Linux workstation, so the stack is staged rather than treated as an always-on full-stack lab.

---

## 1. Host Machine Requirements

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| **OS** | Linux (Ubuntu 24.04 LTS preferred) | Ubuntu 24.04 LTS |
| **CPU** | 4 cores | 8+ cores |
| **RAM** | 8 GB | 16-32 GB |
| **Storage** | 100 GB SSD | 200+ GB NVMe SSD |
| **GPU** | None (CPU inference) | Optional NVIDIA GPU with 8+ GB VRAM |

### 1.1 Practical 8 GB Operating Mode

An 8 GB machine can run Omni-G for development, but not every component at the same time.

- Keep only one heavy profile active at a time: `core` infra, `ai` workloads, or `observability`.
- Stop Prometheus, Grafana, Loki, and Redpanda Console unless you are actively debugging.
- Run one small chat model plus one embedding model in Ollama; do not keep multiple large models pulled and loaded.
- Keep at least 25-30 GB free for Docker layers, Kafka logs, Neo4j stores, and Ollama model files.
- Expect CPU-only inference, slower indexing, and smaller batch sizes during local development.

---

## 2. Core Runtime Tools

These must be installed on the host machine before anything else.

### 2.1 Container Runtime

```bash
# Docker Engine (not Docker Desktop)
# Official docs: https://docs.docker.com/engine/install/ubuntu/
for pkg in docker.io docker-doc docker-compose docker-compose-v2 podman-docker containerd runc; do
  sudo apt-get remove -y "$pkg"
done

sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo \"$VERSION_CODENAME\") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Optional but recommended: run Docker without sudo
sudo usermod -aG docker "$USER"

# Verify
docker --version          # Docker Engine 29.5.0 is the current stable track
docker compose version
```

> Docker's Ubuntu install docs also call out two operational caveats that matter here: published container ports bypass uncomplicated `ufw` defaults, and Docker supports `iptables-nft` / `iptables-legacy` rather than raw `nft` rulesets.

### 2.2 Programming Languages & Runtimes

```bash
# Python toolchain
# Current CPython stable is 3.14.5, but 3.12/3.13 are the safer local dev targets today.
curl -LsSf https://astral.sh/uv/install.sh | sh
uv python install 3.13

# Go 1.26.3 (for Aggregator - high-concurrency ingestion engine)
# https://go.dev/dl/
wget https://go.dev/dl/go1.26.3.linux-amd64.tar.gz
sudo rm -rf /usr/local/go
sudo tar -C /usr/local -xzf go1.26.3.linux-amd64.tar.gz
export PATH=/usr/local/go/bin:$PATH

# Node.js 24 LTS (current LTS line) with nvm, as recommended on nodejs.org/download
# Install nvm from https://github.com/nvm-sh/nvm, then:
nvm install 24
nvm alias default 24

# pnpm via Corepack
npm install --global corepack@latest
corepack enable
corepack use pnpm@latest-11

# Verify
uv --version        # 0.11.14 current stable docs
uv run --python 3.13 python --version
go version          # go1.26.3
node --version      # v24.15.0 current LTS
npm --version       # 11.12.1 current with Node 24.15.0
pnpm --version      # 11.x line
```

### 2.3 Supporting CLI Tools

```bash
sudo apt install -y git make curl jq httpie build-essential pkg-config librdkafka-dev

# Install Python CLI tools with uv instead of pip
uv tool install pre-commit==4.0.1
uv tool install ruff==0.8.2
```

---

## 3. Infrastructure Services (Docker Compose)

All infrastructure runs locally in Docker. On an 8 GB machine, split the stack into profiles such as `core`, `vector`, `ai`, and `observability` instead of starting everything together.

### 3.1 Message Streaming — Apache Kafka (KRaft mode, no ZooKeeper)

- **Image:** `apache/kafka:4.2.0`
- **Purpose:** Central nervous system. All raw events flow through Kafka topics.
- **Key Topics to create on startup:**
  - `raw-feed` — raw ingested events from MCP plugins
  - `processed-entities` — extracted STIX entities from the Processor
  - `analyst-alerts` — high-priority alerts pushed to the Delivery layer
- **UI:** [Redpanda Console](https://github.com/redpanda-data/console) (`docker.redpanda.com/redpandadata/console`) — open-source Kafka UI, but keep it off by default on 8 GB RAM

> Kafka 4.x defaults to KRaft mode. For local development, keep partitions and retention conservative to limit disk and memory use.

### 3.2 Graph Database — Neo4j Community Edition

- **Image:** `neo4j:5.26.26-community`
- **Purpose:** Stores the Knowledge Graph. Nodes = entities (Person, Org, Malware). Edges = relationships (ATTRIBUTED_TO, TARGETS, USES).
- **Query Language:** Cypher
- **Plugins to enable:** APOC for procedures. Do not assume GDS is bundled in Community; keep community detection in a separate Python service unless you explicitly add and license the required plugin stack.
- **Web UI:** Built-in Neo4j Browser at `http://localhost:7474`

> **Alternative:** [FalkorDB](https://github.com/FalkorDB/FalkorDB) (`falkordb/falkordb:latest`) — Redis-based graph DB, lower latency for high-throughput writes. Consider this if Neo4j GDS is overkill in early stages.

### 3.3 Cache & Deduplication — Redis Stack

- **Image:** `redis/redis-stack:7.4.0-v8`
- **Purpose:** SHA-256 content hashing for deduplication, entity blocking cache, sliding-window botnet dedup.
- **Includes:** RedisJSON + RediSearch (needed for entity blocking queries)
- **UI:** RedisInsight at `http://localhost:8001`

### 3.4 Vector Database — Qdrant

- **Image:** `qdrant/qdrant:v1.18.0`
- **Purpose:** Stores entity embeddings for semantic entity resolution ("Robert Smith" ≈ "Bob Smith"). Powers the vector blocking step in the Entity Resolution pipeline.
- **Web UI:** Built-in dashboard at `http://localhost:6333/dashboard`

### 3.5 Object Storage — MinIO

- **Image:** `minio/minio:RELEASE.2025-09-07T16-13-09Z`
- **Purpose:** Replaces GCS/S3. Stores generated audio briefing files, raw document archives, and plugin artifact cache.
- **Web UI:** MinIO Console at `http://localhost:9001`

### 3.6 Observability Stack

| Tool | Image | Purpose |
|------|-------|---------|
| **Prometheus** | `prom/prometheus:v3.11.3` | Metrics scraping from all services |
| **Grafana** | `grafana/grafana:13.0.1-security-01` | Dashboards for Kafka lag, graph write rate, LLM latency |
| **Loki** | `grafana/loki:3.7.2` | Log aggregation (structured JSON logs from all services) |

> Treat the observability stack as optional on this hardware. Turn it on only when you need metrics or log correlation.

---

## 4. Local LLM Runtime (Open-Source, No Cloud)

The Processor's entity extraction uses an LLM. For local-first development:

### 4.1 Ollama

```bash
# Install Ollama (manages model downloads and serves an OpenAI-compatible API)
curl -fsSL https://ollama.com/install.sh | sh

# Pull small models that fit an 8 GB workstation
ollama pull qwen2.5:3b           # Primary local extraction model
ollama pull qwen2.5:1.5b         # Lower-memory fallback
ollama pull nomic-embed-text     # Embedding model for entity vector blocking

# Ollama exposes: http://localhost:11434 (OpenAI-compatible /v1/chat/completions)
```

> Keep the Processor written against the **OpenAI-compatible API** so it works with Ollama locally. On this machine, stop Neo4j/Qdrant or the observability profile before running sustained local inference.

### 4.2 Text-to-Speech (Open-Source Local TTS)

For the audio briefing feature, use [Kokoro TTS](https://github.com/remsky/Kokoro-FastAPI) or [Coqui TTS](https://github.com/coqui-ai/TTS) locally:

```bash
docker pull ghcr.io/remsky/kokoro-fastapi-cpu:v0.2.2
# Exposes an OpenAI-compatible /v1/audio/speech endpoint
```

---

## 5. Python Package Dependencies (Processor & MCP Plugins)

Create a `pyproject.toml` at the project root and use `uv` to lock it. The versions below are the current stable releases verified for this document and are a reasonable starting pin set.

### Processor Service
```
fastapi==0.115.6
pydantic==2.10.3
pydantic-settings==2.6.1
kafka-python-ng==2.2.3
redis[hiredis]==5.2.1
neo4j==5.27.0
qdrant-client==1.12.1
langchain==0.3.10
langgraph==0.2.56
instructor==1.7.0
openai==1.57.2
sentence-transformers==3.3.1
stix2==3.0.1
```

### MCP Plugin SDK
```
mcp==1.0.0
httpx==0.28.1
pydantic==2.10.3
```

---

## 6. Go Module Dependencies (Aggregator)

The Aggregator is written in Go for concurrency. Start from the following current stable module versions in `go.mod`:

```
github.com/confluentinc/confluent-kafka-go/v2 v2.6.1
github.com/go-playground/validator/v10 v10.23.0
github.com/google/uuid v1.6.0
github.com/rs/zerolog v1.33.0
github.com/spf13/viper v1.19.0
```

> If you build the Aggregator directly on the host instead of inside a container, keep `librdkafka-dev` installed.

---

## 7. Frontend Dependencies (Delivery Layer)

```bash
# Scaffold with Next.js 15
pnpm create next-app@latest omni-g-ui --typescript --tailwind --app

# Verified current frontend package versions
pnpm add next@15.0.4 sigma@3.0.1 graphology@0.25.4 graphology-layout-forceatlas2@0.10.1
pnpm add @nivo/network@0.88.0 socket.io-client@4.8.1
pnpm add lucide-react@0.468.0 clsx@2.1.1 tailwind-merge@2.5.5

# Add Radix primitives only for the components you actually use
```

---

## 8. Security & Sandboxing

For running untrusted MCP plugin code locally (Phase 2+):

```bash
# gVisor — kernel-level sandbox for plugin containers
# https://gvisor.dev/docs/user_guide/install/
(
  set -e
  ARCH=$(uname -m)
  URL=https://storage.googleapis.com/gvisor/releases/release/latest/${ARCH}
  wget ${URL}/runsc ${URL}/runsc.sha512
  sha512sum -c runsc.sha512
  chmod a+x runsc
  sudo mv runsc /usr/local/bin
)

# Register gVisor as a Docker runtime
sudo runsc install
sudo systemctl restart docker

# Use in docker-compose: runtime: runsc
```

> For Phase 1 local dev, standard Docker network isolation (`--network=none` + allow-list rules) is sufficient. gVisor is for hardened plugin execution.

---

## 9. Development Tooling

| Tool | Purpose | Install |
|------|---------|---------|
| **VS Code** | IDE with Copilot agent | Already installed |
| **Bruno** | API client (replaces Postman, open-source) | `snap install bruno` |
| **k9s** | Terminal Kubernetes UI (for later K8s phase) | `snap install k9s` |
| **ctop** | Container resource monitor | `sudo apt install ctop` |
| **pre-commit** | Git hooks for linting/formatting | `uv tool install pre-commit==4.0.1` |
| **golangci-lint** | Go linter | See [install docs](https://golangci-lint.run/usage/install/) |
| **ruff** | Python linter + formatter (fast, Rust-based) | `uv tool install ruff==0.8.2` |

---

## 10. Project Directory Structure (Recommended)

```
omni-g/
├── docker-compose.yml          # All infra services
├── docker-compose.override.yml # Local dev overrides
├── Makefile                    # make up, make down, make lint, make test
├── .env.example                # All service configs (copy to .env)
├── prerequisites.md            # This file
│
├── aggregator/                 # Go service — MCP client, Kafka producer
│   ├── cmd/
│   ├── internal/
│   └── go.mod
│
├── processor/                  # Python service — LLM extraction, graph writes
│   ├── src/
│   │   ├── deduplicator/
│   │   ├── extractor/
│   │   ├── resolver/
│   │   └── graph_writer/
│   └── pyproject.toml
│
├── graphrag-service/           # Python service — community detection, briefing generation
│   ├── src/
│   └── pyproject.toml
│
├── delivery/                   # Next.js frontend + WebSocket gateway
│   ├── omni-g-ui/              # Next.js app
│   └── ws-gateway/             # Node.js WebSocket <-> Kafka bridge
│
├── mcp-plugins/                # Individual MCP Server plugins
│   ├── rss-collector/
│   ├── tor-monitor/
│   └── plugin-sdk/             # Shared Python MCP SDK wrapper
│
└── infra/
    ├── prometheus/
    ├── grafana/
    └── neo4j/
        └── init.cypher         # Indexes, constraints on startup
```

---

## 11. Verification Checklist

Run through this before writing the first line of application code:

- [ ] `docker compose --profile core up -d` starts the core infra services without errors
- [ ] Neo4j Browser accessible at `http://localhost:7474` (default creds: `neo4j/neo4j`)
- [ ] Kafka topic `raw-feed` visible in Redpanda Console at `http://localhost:8080`
- [ ] Redis responsive: `docker exec -it redis redis-cli ping` → `PONG`
- [ ] Qdrant health: `curl http://localhost:6333/healthz` returns `200 OK`
- [ ] MinIO Console accessible at `http://localhost:9001`
- [ ] Ollama responding: `curl http://localhost:11434/api/tags` lists pulled models
- [ ] `ollama run qwen2.5:3b "Hello"` returns a response
- [ ] Python env: `uv run --python 3.13 python -c "import neo4j, kafka, pydantic, instructor, stix2; print('OK')"` → `OK`
- [ ] Go build: `cd aggregator && go build ./...` compiles cleanly
- [ ] Node: `cd delivery/omni-g-ui && pnpm install && pnpm build` succeeds

---

## 12. Recommended Build Order

Start small. Each phase produces a working, demonstrable system. On an 8 GB machine, shut down the previous heavy phase before starting the next one.

| Phase | Components | Goal |
|-------|-----------|------|
| **Phase 1** | Kafka + Redis + Neo4j + one Python MCP plugin + Processor | Ingest a raw RSS feed, extract entities, write to graph |
| **Phase 2** | Aggregator (Go) + Entity Resolution + Qdrant | Multi-source ingestion with deduplication and entity merging |
| **Phase 3** | GraphRAG service + Community Detection | Automated graph summarization and briefing generation |
| **Phase 4** | Delivery frontend (Next.js + Sigma.js) + WebSocket gateway | Live interactive graph dashboard |
| **Phase 5** | Audio briefings (Kokoro TTS) + Analyst alerts | "Lean-back" audio intelligence capability |
| **Phase 6** | gVisor sandboxing + multi-tenancy + STIX export | Hardened, production-ready plugin execution |
