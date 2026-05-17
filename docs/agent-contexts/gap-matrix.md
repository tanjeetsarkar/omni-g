# Omni-G Gap Matrix

**Purpose:** living delta between the business-plan vision, the milestone roadmap, and the current Aggregator/Processor implementation.

**Last Updated:** May 17, 2026 — Infrastructure healthcheck correction (Kafka + Kokoro)

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
| Entity resolution | Vector blocking + structural matching + merge thresholds | Not yet implemented | Roadmap-staged gap (M4.1) | Medium |
| Graph persistence | Neo4j write path with STIX-compliant nodes and edges | Not yet implemented | Roadmap-staged gap (M4.2) | Medium |
| GraphRAG | Community detection and summary updates | Not yet implemented | Roadmap-staged gap (M4.3) | Medium |
| Multi-tenant controls | tenant_id propagation in Neo4j queries and WebSocket subscriptions | tenant_id now in Kafka envelope (Aggregator `TenantID` field) and dedup keys; Neo4j/WS layer not yet built | Security gap (partial) | High |
| STIX created_by_ref | Every graph node must carry `created_by_ref` (plugin + analyst ID) | Field present in models and populated in extractor from metadata; Neo4j write path not yet built | Compliance gap (partial) | Medium |

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
- **Infra reliability correction (compose runtime):** Fixed false-negative health checks in `infrastructure/docker-compose.yml` by replacing Kafka probe with a lightweight TCP socket readiness check (`bash -c 'echo > /dev/tcp/localhost/9092'`) instead of unavailable/slow CLI probes, and aligned Kokoro probe/port mapping to the actual service bind port (`8880`) with host mapping `8000:8880`.
- **Kafka listener binding correction:** Kafka listener bind address was updated to `0.0.0.0` (`KAFKA_LISTENERS: PLAINTEXT://0.0.0.0:9092,CONTROLLER://0.0.0.0:29093`) while keeping `KAFKA_ADVERTISED_LISTENERS=PLAINTEXT://kafka:9092`, so in-container localhost health checks and inter-container DNS-based client routing both succeed.

## Next Implementation Reviews

When a change lands, update this matrix by moving items from open to settled or by narrowing the remaining gap. If a change introduces a new deviation, add it here immediately rather than waiting for a broader architecture review.