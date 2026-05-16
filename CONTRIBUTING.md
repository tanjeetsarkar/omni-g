# Contributing to Omni-G

## Prerequisites

Ensure you have all tools installed per [prerequisites.md](prerequisites.md):
- Docker 29.5+ with Compose v2
- Go 1.26+
- Python 3.13+ with uv 0.11+
- Node.js 24 LTS with pnpm 11+
- pre-commit

## Quick Start

```bash
git clone <repo> omni-g
cd omni-g

# Install pre-commit hooks
pre-commit install

# Start core infrastructure
docker compose -f infrastructure/docker-compose.yml --profile core up -d

# Build and test all services
make test-all        # or run each service manually (see below)
```

## Service Development

### Aggregator (Go)

```bash
cd services/aggregator
go mod download
go test ./...
go build ./cmd/aggregator
```

### Processor (Python)

```bash
cd services/processor
uv sync --dev
uv run pytest
uv run ruff check src/ tests/
uv run mypy src/
```

### Delivery (TypeScript)

```bash
cd services/delivery
pnpm install
pnpm test
pnpm build
pnpm dev  # starts dev server on :3000
```

## Pre-Commit Hooks

Pre-commit hooks run automatically on `git commit`. They enforce:
- **Go**: `gofmt`, `go vet`, unit tests
- **Python**: `ruff` (lint + format)
- **TypeScript**: `prettier` (format)

To run all hooks manually:

```bash
pre-commit run --all-files
```

## CI/CD

The GitHub Actions workflow (`.github/workflows/build.yml`) runs on every push and pull request to `main` and `develop`. It:
1. Builds and tests all three services
2. Lints and type-checks each service
3. Builds Docker images as a smoke test

All CI checks must pass before merging to `main`.

## Docker Compose Profiles

| Profile         | Services                              | RAM   |
|-----------------|---------------------------------------|-------|
| `core`          | Kafka, Redis, Neo4j                   | ~3 GB |
| `vector`        | Qdrant                                | +1 GB |
| `ai`            | Ollama, Kokoro TTS                    | +2 GB |
| `observability` | Prometheus, Grafana, Loki             | +1 GB |
| `storage`       | MinIO                                 | +256 MB |
| `services`      | Aggregator, Processor, Delivery       | +512 MB |
| `all`           | Everything                            | ~8 GB |

Start with `--profile core` during development; add profiles as needed.

## Commit Convention

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(aggregator): add Kafka retry logic
fix(processor): handle empty LLM response
docs: update API endpoint table
chore(ci): pin golangci-lint version
```

Types: `feat`, `fix`, `docs`, `chore`, `refactor`, `test`, `perf`

## Branch Strategy

- `main` — stable, always deployable
- `develop` — integration branch
- `feat/<name>` — feature branches off `develop`
- `fix/<name>` — bugfix branches

## Code Review

All changes to `main` require at least one approval. The reviewer should:
- Verify tests pass and coverage is maintained (>80% target)
- Check for STIX compliance on data model changes
- Validate no cross-tenant data leakage on multi-tenant changes
- Confirm Prometheus metrics are updated for new code paths
