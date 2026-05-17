# Omni-G Gap Matrix

**Purpose:** living delta between the business-plan vision, the milestone roadmap, and the current Aggregator/Processor implementation.

**Last Updated:** May 17, 2026 — CI reliability hardening (Aggregator lint toolchain, Processor Ruff formatting, Delivery no-test policy)

## Scope

This document should be updated after every implementation change. Capture only material deltas:
- what is already aligned with the vision
- what is intentionally staged in the roadmap
- what is still missing or only partially implemented
- what doc or naming drift should be normalized next

## Current Snapshot

### Confirmed Alignment

- Aggregator remains the ingestion edge and publishes to Kafka rather than calling downstream systems directly.
- Processor remains the intelligence core and owns validation-sidecar compatibility, extraction scaffolding, and Kafka consumption scaffolding.
- The roadmap correctly stages the larger intelligence features behind M3.2-M4.3, so the current codebase is not expected to be fully realized yet.

### Open Gaps Versus Vision

| Area | Vision | Current Implementation | Gap Type | Priority |
|------|--------|------------------------|----------|----------|
| Entity resolution | Vector blocking + structural matching + merge thresholds | Fully implemented: `EntityResolver` with Qdrant vector blocking, Neo4j structural matching, merge tiers (>95% AUTO_MERGE, 50-95% AMBIGUOUS, <50% NEW_ENTITY), SAME_AS lifecycle tracking, Prometheus metrics; wired into `ProcessingPipeline` via `startup_consumer`; 37 tests, 97% coverage | ✅ Closed (M4.1) | — |
| Graph persistence | Neo4j write path with STIX-compliant nodes and edges | Fully implemented: `GraphSchemaManager` (unique constraints + 3 index types per STIX label), `GraphPersistenceService` with `upsert_entity`, `upsert_relationship`, `persist_extraction` (single atomic transaction, auto-rollback on failure); STIX type → PascalCase label mapping; STIX rel-type → Neo4j edge type mapping; `GRAPH_WRITE_LATENCY` Histogram and `GRAPH_WRITE_ERRORS` Counter; wired into `ProcessingPipeline` (Step 5) and `startup_consumer` in `main.py` | ✅ Closed (M4.2) | — |
| GraphRAG | Community detection and summary updates | Fully implemented: `CommunityDetector` (GDS Leiden/Louvain with Python connected-components fallback, plus `detect_communities_for_entity` for 2-hop incremental); `CommunitySummarizer` (Ollama + OpenAI backends, template fallback); `GraphRAGIndexer` (full + incremental indexing, background periodic task, Prometheus metrics: latency, community gauge, summaries updated, update frequency); wired into `ProcessingPipeline` (Step 6) and `startup_consumer`; 10 new GraphRAG tests; all 131 tests pass | ✅ Closed (M4.3) | — |
| Multi-tenant controls | tenant_id propagation in Neo4j queries and WebSocket subscriptions | tenant_id now in Kafka envelope (Aggregator `TenantID` field) and dedup keys; Neo4j/WS layer not yet built | Security gap (partial) | High |
| STIX created_by_ref | Every graph node must carry `created_by_ref` (plugin + analyst ID) | Field present in models and populated in extractor from metadata; Neo4j write path not yet built | Compliance gap (partial) | Medium |
| Delivery test baseline | CI should enforce Delivery unit tests without masking regressions | CI now explicitly uses `jest --passWithNoTests` to keep pipeline green while no tracked Delivery tests match `testMatch`; this is temporary until baseline tests are committed | Quality gap (temporary) | Medium |

### Already Upgraded Enough To Treat As Settled For Now

- Kafka-based decoupling is in place at the service boundary.
- Validation sidecar wiring exists between Aggregator and Processor.
- Aggregator scheduling, metrics, and shutdown handling are already scaffolded.
- Processor health, readiness, and model scaffolding are already in place.
- **M3.1 remaining gaps (closed):** Aggregator now performs dynamic MCP `tools/list` discovery at startup and on every poll cycle via `DiscoverTools`; `RawEvent` envelope carries `PluginVersion`, `PluginName`, `IngestLatencyMs`, `SchemaVersion`, `TenantID`; validation sidecar enforces URL format, non-empty payload, no null top-level values, and content-key presence with structured error objects — 7 Go packages ok, 36 Python tests pass.
- **M3.2 Deduplication:** `ContentDeduplicator` with SHA-256, sliding-window TTL, atomic Lua, tenant isolation, RediSearch clustering, and fail-open semantics — 12/12 tests passing.
- **M3.3 LLM Extraction:** `LLMExtractor` wired to Ollama via `instructor`; primary→fallback degradation on timeout/API error; semaphore rate limiting; confidence scaling by entity count+diversity; `extract_batch` with exception isolation; `ExtractionResult` carries `plugin_id`/`plugin_version` — 39/39 tests passing.
- **STIX models (closed):** Full SDO coverage — `ThreatActor`, `Malware`, `Identity`, `AttackPattern`, `Campaign`, `Indicator`, `Location`, `Relationship` (SRO), `STIXBundle`; `created_by_ref` on base model; `custom_properties` extensibility.
- **M3.4 Consumer pipeline (closed — fully upgraded):** `ProcessingPipeline` class in `src/processor/pipeline.py` orchestrates schema validation → dedup → LLM extraction → entity-resolution stub (M4.1); `RawEventEnvelope` Pydantic model enforces payload schema (mirrors `/validate` endpoint rules); `SchemaViolationError` raised on invalid events so the consumer routes them to DLQ with `error_type=SchemaViolationError`; three new Prometheus metrics — `processor_extraction_confidence` histogram (buckets 0.1…1.0), `processor_schema_violations_total` counter, `processor_dedup_drops_total` counter with `tenant_id` label; `KAFKA_NUM_WORKERS` setting launches N consumer tasks (same `group_id`, Kafka rebalances partitions automatically); `main.py` lifespan manages the full task list; 19 new pipeline tests + 1 new consumer test; all 68 tests pass.
- **Quality hardening (no roadmap scope change):** Processor lint/type issues were remediated without behavior changes: fixed test fixture typing and line-length violations, removed stale `# type: ignore` comments, and tightened local sequence typing in confidence calculation. Validation: `ruff check src tests`, `mypy src`, and `pytest` all pass (68 tests).
- **M4.1 Entity Resolution Service (closed):** `EntityResolver` implements two-stage resolution: (1) Qdrant vector blocking using hash-based embeddings (placeholder for Phase 5 real embeddings) with per-tenant collections; (2) Neo4j structural matching with exact name/alias Cypher query + co-occurrence analysis (≥2 shared relationship targets). Merge tiers: AUTO_MERGE (≥0.95), AMBIGUOUS (0.50–0.95, creates SAME_AS edge), NEW_ENTITY (<0.50). Entity lifecycle tracked via Neo4j MERGE with `created_at`/`updated_at`. Prometheus metrics: `processor_resolution_decisions_total`, `processor_resolution_latency_seconds`, `processor_false_positive_alerts_total`, `processor_same_as_merges_total`. Wired into `ProcessingPipeline` (Step 4) and `startup_consumer` in `main.py` with AsyncDriver + AsyncQdrantClient; connections properly closed in finally block. 37 unit+integration tests, 97% resolver coverage, 107 total tests passing.
- **M4.2 Graph Persistence (closed):** `GraphSchemaManager` initialises all Neo4j constraints (unique on `id` per STIX label) and 3 index types (tenant, confidence, timestamps) for 7 STIX node labels at startup. `GraphPersistenceService` provides `upsert_entity` (MERGE with PascalCase label + `STIXEntity` secondary label), `upsert_relationship` (STIX rel-type → Neo4j edge label mapping for 5 known types + generic fallback), and `persist_extraction` (all SDOs then SROs in a single transaction; auto-rollback on failure). Prometheus: `GRAPH_WRITE_LATENCY` Histogram and `GRAPH_WRITE_ERRORS` Counter. Wired into `ProcessingPipeline` (Step 5) and `startup_consumer`. 14 new graph tests.
- **M4.3 GraphRAG Indexing (closed):** `CommunityDetector` tries GDS Leiden/Louvain on a projected graph, falls back to Python union-find connected-components when GDS is unavailable; `detect_communities_for_entity` runs incremental 2-hop subgraph detection. `CommunitySummarizer` fetches entity+relationship context, builds an analyst-style prompt, calls Ollama (or OpenAI if key set), falls back to a template on error, and writes `community_id`/`community_summary`/`community_updated_at` to member nodes. `GraphRAGIndexer` orchestrates full and incremental passes, supports a background periodic task, and emits 4 Prometheus metrics. Wired into `ProcessingPipeline` (Step 6) and `startup_consumer`. 10 new GraphRAG tests. All 131 tests pass.
- **CI reliability hardening (no roadmap scope change):** Aggregator lint step no longer depends on a prebuilt `golangci-lint` binary compiled with an older Go toolchain; workflow now installs a pinned `golangci-lint` version from source using the job's Go 1.26 environment before linting. Processor code was reformatted to satisfy enforced Ruff format checks. Delivery CI test command now includes `--passWithNoTests` to make current no-test state explicit until tracked baseline tests are added.

 in `infrastructure/docker-compose.yml` by replacing Kafka probe with a lightweight TCP socket readiness check (`bash -c 'echo > /dev/tcp/localhost/9092'`) instead of unavailable/slow CLI probes, and aligned Kokoro probe/port mapping to the actual service bind port (`8880`) with host mapping `8000:8880`.
- **Kafka listener binding correction:** Kafka listener bind address was updated to `0.0.0.0` (`KAFKA_LISTENERS: PLAINTEXT://0.0.0.0:9092,CONTROLLER://0.0.0.0:29093`) while keeping `KAFKA_ADVERTISED_LISTENERS=PLAINTEXT://kafka:9092`, so in-container localhost health checks and inter-container DNS-based client routing both succeed.

## Next Implementation Reviews

When a change lands, update this matrix by moving items from open to settled or by narrowing the remaining gap. If a change introduces a new deviation, add it here immediately rather than waiting for a broader architecture review.