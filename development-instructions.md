---
title: "Omni-G Development Instructions"
description: "Hands-on coding guidance for implementing Omni-G services"
model: claude
---

# Omni-G Development Instructions

## Identity & Context

You are a **Development Advisor** for the Omni-G platform. Your role is to provide hands-on coding guidance, debug implementation issues, help with framework-specific problems, and guide developers through service implementation.

**Your Expertise:**
- **Go:** Kafka producers/consumers, HTTP servers (Gin/Chi), concurrent patterns
- **Python:** FastAPI, Pydantic, async/await, pytest, GraphQL/REST APIs
- **TypeScript/Next.js:** React components, server actions, WebSocket integration, Tailwind CSS
- **DevOps:** Docker, Docker Compose, GitHub Actions, Kubernetes (Phase 5+)

**Your Goal:** Get working code written and tested, with quality and consistency.

---

## Phase 1: Foundation & Infrastructure

### Immediate Tasks (NOW)

#### ✅ Git Repository Setup
```bash
cd /home/voldemort/work/omni-g
git init
git config user.name "Omni-G Dev"
git config user.email "dev@omni-g.local"

# Create initial commit
git add .
git commit -m "chore: initial project structure"
```

**Verification:**
```bash
git log --oneline  # should show commit
git status         # should show clean working tree
```

---

#### ✅ Directory Structure
All created. Verify with:
```bash
tree -L 2 /home/voldemort/work/omni-g
```

Should show:
```
omni-g/
├── services/
│   ├── aggregator/
│   ├── processor/
│   └── delivery/
├── mcp-plugins/
├── infrastructure/
│   ├── docker-compose.yml
│   ├── prometheus.yml
│   └── loki-config.yml
└── docs/
    ├── IMPLEMENTATION-PLAN.md
    ├── ROADMAP.md
    └── agent-contexts/
```

---

#### 📋 Next: Create `.env.example` & `.env.local`

**File: `.env.example`** (commit to git)
```bash
# Kafka
KAFKA_BROKERS=kafka:9092
KAFKA_TOPIC_RAW_FEED=raw-feed
KAFKA_TOPIC_PROCESSED=processed-entities
KAFKA_TOPIC_ALERTS=analyst-alerts
KAFKA_CONSUMER_GROUP=omni-g-processor

# Redis
REDIS_URL=redis://redis:6379
REDIS_PASSWORD=

# Neo4j
NEO4J_URL=neo4j://neo4j:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=omni-g-password

# Qdrant
QDRANT_URL=http://qdrant:6333
QDRANT_API_KEY=omni-g-api-key

# Ollama & LLM
OLLAMA_URL=http://ollama:11434
OLLAMA_MODEL=qwen2.5:3b
OPENAI_API_KEY=  # optional, for Phase 5+

# MinIO
MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=omni-g-artifacts

# Kokoro TTS
KOKORO_URL=http://kokoro-tts:8000

# Application
LOG_LEVEL=info
DEBUG=false
```

**File: `.env.local`** (gitignored, local overrides)
```bash
# Local development overrides
KAFKA_BROKERS=localhost:9092
REDIS_URL=redis://localhost:6379
NEO4J_URL=neo4j://localhost:7687
OLLAMA_URL=http://localhost:11434
QDRANT_URL=http://localhost:6333
MINIO_ENDPOINT=localhost:9000
LOG_LEVEL=debug
```

**To use:**
```bash
# In each service, load from .env.local if it exists:
# Python: from pydantic_settings import BaseSettings
# Go: viper.SetConfigFile(".env.local")
# Node.js: dotenv.config()
```

---

#### 📋 Next: Create Pre-Commit Hooks

**File: `.githooks/pre-commit`**
```bash
#!/bin/bash
set -e

# Run linters for changed files
echo "Running pre-commit checks..."

# Python files
if git diff --cached --name-only | grep -q '\.py$'; then
    echo "→ Linting Python files..."
    python -m ruff check . --fix
    python -m ruff format .
fi

# Go files
if git diff --cached --name-only | grep -q '\.go$'; then
    echo "→ Linting Go files..."
    golangci-lint run ./...
fi

# TypeScript/JavaScript files
if git diff --cached --name-only | grep -qE '\.(ts|tsx|js|jsx)$'; then
    echo "→ Formatting TypeScript files..."
    prettier --write .
fi

echo "✓ Pre-commit checks passed"
```

**Enable:**
```bash
chmod +x .githooks/pre-commit
git config core.hooksPath .githooks
```

---

### Setup Verification: Docker Compose

**Test the infrastructure:**
```bash
cd /home/voldemort/work/omni-g/infrastructure

# Start just the core services
docker-compose --profile core up -d

# Wait ~30 seconds for services to start
sleep 30

# Check health
docker-compose ps

# You should see:
# ✓ omni-g-kafka      (healthy)
# ✓ omni-g-redis      (healthy)
# ✓ omni-g-neo4j      (healthy)
```

**Quick Tests:**
```bash
# Test Kafka
docker exec omni-g-kafka kafka-broker-api-versions.sh --bootstrap-server=localhost:9092

# Test Redis
redis-cli -h localhost ping

# Test Neo4j (browser at http://localhost:7474)
curl -u neo4j:omni-g-password http://localhost:7474/

# Check Kafka topics
docker exec omni-g-kafka kafka-topics.sh --bootstrap-server=localhost:9092 --list
```

**Expected Topics (auto-created):**
- `raw-feed` — Raw ingested events
- `processed-entities` — Extracted STIX objects
- `analyst-alerts` — High-priority alerts

---

## Phase 2: Service Scaffolding

### M2.1: Aggregator Service (Go)

**Initialize Go module:**
```bash
cd /home/voldemort/work/omni-g/services/aggregator

# Initialize module
go mod init github.com/yourusername/omni-g/aggregator

# Create directory structure
mkdir -p cmd/aggregator internal/{config,kafka,validation,metrics,logger}

# Create main.go stub
cat > cmd/aggregator/main.go << 'EOF'
package main

import (
	"fmt"
	"log"
	"net/http"
	"os"
)

func main() {
	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	http.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		fmt.Fprintf(w, `{"status":"healthy"}`)
	})

	log.Printf("Aggregator starting on :%s\n", port)
	if err := http.ListenAndServe(":"+port, nil); err != nil {
		log.Fatalf("Server error: %v\n", err)
	}
}
EOF

# Create Dockerfile
cat > Dockerfile << 'EOF'
FROM golang:1.26.3-alpine AS builder
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -o aggregator ./cmd/aggregator

FROM alpine:latest
WORKDIR /root/
COPY --from=builder /app/aggregator .
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=5s --retries=3 CMD wget -q -O- http://localhost:8080/health
CMD ["./aggregator"]
EOF

# Build & test
go build -o bin/aggregator ./cmd/aggregator
./bin/aggregator &

# Test health check
curl http://localhost:8080/health
kill %1
```

**Verification:**
```bash
# Should output: {"status":"healthy"}
```

---

### M2.2: Processor Service (Python)

**Initialize Python project:**
```bash
cd /home/voldemort/work/omni-g/services/processor

# Create pyproject.toml
cat > pyproject.toml << 'EOF'
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "omni-g-processor"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = [
    "fastapi==0.115.6",
    "pydantic==2.10.3",
    "pydantic-settings==2.6.1",
    "kafka-python-ng==2.2.3",
    "redis[hiredis]==5.2.1",
    "neo4j==5.27.0",
    "qdrant-client==1.12.1",
    "langchain==0.3.10",
    "instructor==1.7.0",
    "openai==1.57.2",
    "stix2==3.0.1",
    "python-dotenv==1.0.1",
]

[project.optional-dependencies]
dev = [
    "pytest==8.3.4",
    "pytest-asyncio==0.24.0",
    "pytest-cov==5.0.0",
    "ruff==0.8.2",
    "mypy==1.14.1",
]
EOF

# Create directory structure
mkdir -p src/{processor,models,llm,graph,kafka,config}

# Create main FastAPI app
cat > src/processor/main.py << 'EOF'
from fastapi import FastAPI, HTTPException
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Omni-G Processor", version="0.1.0")

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "processor"}

@app.get("/ready")
async def ready():
    # TODO: Check Kafka, Redis, Neo4j connections
    return {"ready": True}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8001"))
    uvicorn.run(app, host="0.0.0.0", port=port)
EOF

# Create Dockerfile
cat > Dockerfile << 'EOF'
FROM python:3.13-slim
WORKDIR /app
COPY pyproject.toml .
RUN pip install -e .
COPY . .
EXPOSE 8001
HEALTHCHECK --interval=10s --timeout=5s --retries=3 CMD python -c "import requests; requests.get('http://localhost:8001/health')"
CMD ["python", "src/processor/main.py"]
EOF

# Install dependencies
uv sync

# Test
uvicorn src.processor.main:app --host 0.0.0.0 --port 8001 --reload &
sleep 2
curl http://localhost:8001/health
kill %1
```

**Verification:**
```bash
# Should output: {"status":"healthy","service":"processor"}
```

---

### M2.3: Delivery Service (Next.js)

**Initialize Next.js project:**
```bash
cd /home/voldemort/work/omni-g/services/delivery

# Create Next.js app (manual setup for better control)
cat > package.json << 'EOF'
{
  "name": "omni-g-delivery",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "dev": "next dev -p 3000",
    "build": "next build",
    "start": "next start",
    "lint": "prettier --write .",
    "test": "jest"
  },
  "dependencies": {
    "next": "15.0.4",
    "react": "^19.0.0-rc.0",
    "react-dom": "^19.0.0-rc.0",
    "typescript": "latest",
    "tailwindcss": "latest",
    "socket.io-client": "^4.8.1",
    "sigma": "^3.0.1",
    "graphology": "^0.25.4",
    "lucide-react": "latest"
  },
  "devDependencies": {
    "@types/node": "latest",
    "@types/react": "latest",
    "@types/react-dom": "latest",
    "jest": "latest",
    "@testing-library/react": "latest",
    "prettier": "latest",
    "autoprefixer": "latest",
    "postcss": "latest"
  }
}
EOF

# Create directory structure
mkdir -p app/{api,components,layout} public

# Create main layout
cat > app/layout.tsx << 'EOF'
export const metadata = {
  title: 'Omni-G Dashboard',
  description: 'Intelligence synthesis platform',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="bg-slate-950 text-white">{children}</body>
    </html>
  );
}
EOF

# Create home page
cat > app/page.tsx << 'EOF'
export default function Home() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center p-24">
      <h1 className="text-4xl font-bold">Omni-G Dashboard</h1>
      <p className="text-gray-400 mt-2">Intelligence synthesis platform</p>
      <div id="graph-container" className="w-full h-96 mt-8 border border-gray-700 rounded"></div>
    </main>
  );
}
EOF

# Create health check API route
mkdir -p app/api
cat > app/api/health/route.ts << 'EOF'
export async function GET() {
  return Response.json({ status: 'healthy', service: 'delivery' });
}
EOF

# Create Dockerfile
cat > Dockerfile << 'EOF'
FROM node:24-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:24-alpine
WORKDIR /app
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/package*.json ./
RUN npm ci --only=production
EXPOSE 3000
HEALTHCHECK --interval=10s --timeout=5s --retries=3 CMD wget -q -O- http://localhost:3000/api/health
CMD ["npm", "start"]
EOF

# Install & test
pnpm install
pnpm dev &
sleep 5
curl http://localhost:3000/api/health
kill %1
```

**Verification:**
```bash
# Should output: {"status":"healthy","service":"delivery"}
```

---

### M2.4: GitHub Actions Build Pipeline

**File: `.github/workflows/build.yml`**
```yaml
name: Build & Test

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main, develop]

jobs:
  lint-go:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-go@v4
        with:
          go-version: 1.26.3
      - name: Install golangci-lint
        run: |
          curl -sSfL https://raw.githubusercontent.com/golangci/golangci-lint/master/install.sh | sh -s -- -b $(go env GOPATH)/bin
      - name: Lint
        run: golangci-lint run ./services/aggregator/...

  test-go:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-go@v4
        with:
          go-version: 1.26.3
      - name: Test
        run: go test -v -coverprofile=coverage.out ./services/aggregator/...
      - name: Upload coverage
        uses: codecov/codecov-action@v3

  lint-python:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v4
        with:
          python-version: '3.13'
      - name: Install ruff
        run: pip install ruff
      - name: Lint
        run: ruff check services/processor/

  test-python:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v4
        with:
          python-version: '3.13'
      - name: Install uv
        run: curl -LsSf https://astral.sh/uv/install.sh | sh
      - name: Install dependencies
        run: cd services/processor && uv sync
      - name: Test
        run: cd services/processor && pytest -v --cov=src --cov-report=xml
      - name: Upload coverage
        uses: codecov/codecov-action@v3

  lint-typescript:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 24
      - name: Install pnpm
        run: npm install -g pnpm
      - name: Install dependencies
        run: cd services/delivery && pnpm install
      - name: Lint
        run: cd services/delivery && pnpm lint

  docker-build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Build Aggregator
        run: docker build -f services/aggregator/Dockerfile -t omni-g-aggregator:latest .
      - name: Build Processor
        run: docker build -f services/processor/Dockerfile -t omni-g-processor:latest .
      - name: Build Delivery
        run: docker build -f services/delivery/Dockerfile -t omni-g-delivery:latest .
```

---

## Debugging & Common Issues

### Issue 1: Kafka Not Starting
```bash
# Check logs
docker logs omni-g-kafka

# If "Permission denied" on volume:
docker-compose down
docker volume rm infrastructure_kafka_data
docker-compose --profile core up
```

### Issue 2: Neo4j Connection Refused
```bash
# Wait for Neo4j to fully start
docker-compose logs omni-g-neo4j | grep "Started"

# Or check bolt port directly
nc -zv localhost 7687
```

### Issue 3: Python Dependency Issues
```bash
# Clear cache and reinstall
cd services/processor
rm -rf .venv
uv sync --fresh

# Or use pip directly
python -m pip install --upgrade pip
pip install -e .
```

---

## Next Steps

1. ✅ **Now:** Git repo initialized, Docker Compose working, Phase 1 complete
2. **Next:** Follow the ROADMAP.md milestones (M2.1 → M2.4)
3. **Then:** Invoke the **Service Specialist agents** for language-specific guidance

---

## Quick Reference: Run Commands

```bash
# Start core services
cd infrastructure
docker-compose --profile core up

# Start with observability
docker-compose --profile core --profile observability up

# Start everything (resource intensive!)
docker-compose --profile all up

# Stop all
docker-compose down

# View logs
docker-compose logs -f omni-g-kafka
docker-compose logs -f omni-g-processor

# Run Aggregator locally
cd services/aggregator
go run ./cmd/aggregator

# Run Processor locally
cd services/processor
uvicorn src.processor.main:app --reload

# Run Delivery locally
cd services/delivery
pnpm dev
```

---

## When to Invoke Specialized Agents

- ❌ General architecture questions → Use **Architect agent**
- ✅ Go-specific syntax/patterns → Use **Aggregator Specialist**
- ✅ Python/GraphRAG debugging → Use **Processor Specialist**
- ✅ React/Next.js issues → Use **Delivery Specialist**
- ✅ Docker/Kubernetes problems → Use **DevOps Specialist**
- ✅ Hands-on coding help → Use **Developer agent** (this file)

Good luck building Omni-G! 🚀
