# Omni-G V2 Infrastructure Transition

## Objective

Keep the current runtime stack as intact as possible while shifting the Processor to Celery-based orchestration.

## Runtime Baseline Kept in V2

V2 keeps these core platform dependencies:

- Kafka — ingestion backbone and downstream event bus
- Redis — deduplication and Celery broker/result storage
- Neo4j — knowledge graph
- Qdrant — semantic search and resolution support
- Ollama-compatible LLM runtime — extraction and analytical generation
- MinIO — briefing and artifact storage
- Prometheus, Grafana, and Loki — observability

## Processor Runtime Change

### V1 runtime

- FastAPI process owns HTTP endpoints and Kafka consumers.
- Each consumer worker builds the full dependency graph.
- `ProcessingPipeline.process()` runs inline inside the consumer callback.
- APScheduler-style logic handles scheduled briefing work.

### V2 runtime

- FastAPI process keeps HTTP endpoints and Kafka intake coordination.
- Kafka consumer remains the intake boundary.
- Kafka consumer dispatches Celery tasks instead of doing all analysis inline.
- Celery workers own analytical execution.
- Celery Beat owns scheduled work.

## Deployment Shape

### Required services kept

- `kafka`
- `redis`
- `neo4j`
- `qdrant`
- `aggregator`
- `processor`
- `delivery`
- `gateway`

### New runtime roles

- `processor-worker` — Celery worker for analysis execution
- `processor-beat` — Celery Beat for recurring work

### Optional runtime role

- `flower` — task monitoring UI for local debugging and operations

## Redis Usage Split

V2 should reuse Redis rather than introduce a new broker.

Recommended separation:

- Redis logical DB 0 or current namespace — deduplication data
- Redis logical DB 1 — Celery broker
- Redis logical DB 2 — Celery result backend

If logical databases are not desirable in all environments, use separate key prefixes with the same operational separation documented.

## Queue Topology

Initial queue set:

- `process_event` — coarse event processing task
- `analysis_enrichment` — non-critical background analysis
- `graph_maintenance` — summaries, graph maintenance, re-index work
- `briefing_generation` — audio and briefing outputs
- `scheduled_collection_review` — periodic KIQ and collection review

## Failure Model

### Keep in Kafka DLQ

- malformed envelopes
- validation-sidecar mismatches
- non-recoverable ingestion contract failures

### Handle through Celery retry or task failure

- transient LLM timeouts
- temporary Neo4j or Qdrant failures
- temporary downstream publication failures
- scheduled analysis job failures

## Local Development Path

The local development path must remain lightweight.

Recommended profiles:

- baseline path: current non-Celery stack for basic development and UI work
- orchestration path: current stack plus `processor-worker` and `processor-beat`
- optional diagnostics path: add `flower` only when debugging queues

## Compose and Config Changes

Planned changes:

- add Celery settings to Processor configuration
- add worker and beat commands to compose
- document environment variables for broker URL, result backend, concurrency, and queue routing
- document low-memory defaults for local development

## Validation Targets

Infrastructure work should be considered complete when:

- Kafka intake still works with the existing topics
- Processor consumer enqueues tasks successfully
- Celery worker can execute the coarse `process_event` task end to end
- Beat can trigger at least one scheduled analytical task
- queue health and failure visibility appear in observability docs
