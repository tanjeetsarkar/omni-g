# Omni-G Roadmap (Milestone-Based)

**Last Updated:** May 16, 2026  
**Status:** Foundation Phase Active

This roadmap outlines the sequential milestones for building Omni-G. Each milestone has clear deliverables, success criteria, and dependencies. No time estimates—sequencing is based on logical dependencies.

---

## M1: Project Foundation

**Status:** 🟢 IN PROGRESS  
**Focus:** Infrastructure, version control, documentation framework

### Milestones

#### M1.1: Git Repository & Development Environment
- [x] Initialize Git repository
- [x] Create `.gitignore` (Python, Node.js, Go)
- [x] Create `.editorconfig` for consistent formatting
- [x] Create `.dockerignore`
- [x] Configure pre-commit hooks (.githooks)
- [x] Add CONTRIBUTING.md template
- [ ] Add CODE_OF_CONDUCT.md

**Dependencies:** None  
**Verification:** `git log` shows clean commits, `pre-commit run --all-files` passes

---

#### M1.2: Directory Structure
- [x] Create `/services` directory structure
- [x] Create `/infrastructure` with docker-compose base
- [x] Create `/mcp-plugins` directory
- [x] Create `/docs` with subdirectories
- [x] Add README.md to each service root explaining purpose

**Dependencies:** M1.1  
**Verification:** All directories created, service READMEs explain module purpose

---

#### M1.3: Infrastructure-as-Code (Docker Compose)
- [x] Create base `docker-compose.yml` with all services
- [x] Define multi-profile setup (core, vector, ai, observability, storage, services)
- [x] Add resource constraints (8 GB machine awareness)
- [x] Add health checks for all services
- [x] Create Prometheus configuration
- [x] Create Loki configuration
- [x] Create `.env.example` with all environment variables
- [x] Create `.env.local` gitignored template
- [x] Document profile-specific setup instructions

**Dependencies:** M1.2  
**Verification:** `docker-compose --profile core up` succeeds, all services healthy

---

#### M1.4: Copilot Instructions & Agent Framework
- [x] Create `.copilot-instructions.md` (architecture validation mode)
- [x] Create `development-instructions.md` (hands-on coding mode)
- [x] Create `AGENTS.md` with:
  - Omni-G Architect agent definition
  - Omni-G Developer agent definition
  - Service Specialist agents (Aggregator, Processor, Delivery)
  - DevOps agent definition
- [x] Create `/docs/agent-contexts/`:
  - `architect.md` — design validation context
  - `developer.md` — implementation guidance
  - `aggregator-specialist.md` — Go/Kafka specifics
  - `processor-specialist.md` — Python/GraphRAG specifics
  - `delivery-specialist.md` — Next.js/WebSocket specifics
  - `devops-specialist.md` — Docker/Kubernetes/observability

**Dependencies:** M1.3  
**Verification:** All agent files created, Copilot can invoke agents without errors

---

#### M1.5: Documentation Foundation
- [x] Create `docs/IMPLEMENTATION-PLAN.md` (this document expanded)
- [x] Create `docs/ROADMAP.md` (milestone sequencing)
- [ ] Create `docs/SECURITY.md` (threat model, mitigations)
- [ ] Create `docs/ARCHITECTURE.md` (high-level component overview)
- [ ] Create `docs/GLOSSARY.md` (terminology reference)
- [ ] Create root `README.md` with project overview

**Dependencies:** M1.2, M1.4  
**Verification:** Documentation complete, links verified, no broken references

---

## M2: Service Scaffolding

**Status:** � COMPLETE  
**Focus:** Service initialization, build pipelines, test frameworks

### Milestones

#### M2.1: Aggregator Service (Go)
- [x] Initialize Go module: `go mod init`
- [x] Create `/cmd/aggregator` with main.go
- [x] Implement HTTP health check endpoint (`:8080/health`)
- [x] Create `/internal/kafka` directory structure
- [x] Create `/internal/validation` directory structure
- [x] Create Dockerfile with multi-stage build
- [x] Add unit test skeleton (testify + table-driven tests)
- [x] Document aggregator responsibilities in README

**Dependencies:** M1.2, M1.3  
**Verification:**
- `go mod tidy` succeeds
- `go build ./cmd/aggregator` produces binary
- `docker build -f services/aggregator/Dockerfile .` succeeds
- Health check endpoint responds to curl

---

#### M2.2: Processor Service (Python)
- [x] Initialize Python project with pyproject.toml
- [x] Configure uv for dependency management
- [x] Create FastAPI main application
- [x] Implement HTTP health check endpoint (`:8001/health`)
- [x] Create `/src/processor`, `/src/models`, `/src/llm` directories
- [x] Create `/src/kafka` consumer skeleton
- [x] Create Dockerfile with Python 3.13
- [x] Add pytest fixtures for Kafka/Redis/Neo4j
- [x] Document processor responsibilities in README

**Dependencies:** M1.2, M1.3  
**Verification:**
- `uv sync` installs dependencies
- `fastapi dev src/processor/main.py` starts server
- `docker build -f services/processor/Dockerfile .` succeeds
- `pytest src/` discovers all tests

---

#### M2.3: Delivery Service (Next.js Frontend)
- [x] Initialize Next.js 15 with TypeScript + Tailwind
- [x] Create WebSocket gateway stub in `/app/api/ws`
- [x] Create Sigma.js graph component skeleton
- [x] Configure Socket.io client
- [x] Create Dockerfile for Next.js production build
- [x] Add Jest test configuration
- [x] Document delivery responsibilities in README

**Dependencies:** M1.2, M1.3  
**Verification:**
- `npm run dev` starts development server on :3000
- `npm run build` succeeds
- `docker build -f services/delivery/Dockerfile .` succeeds
- `npm test` discovers all tests

---

#### M2.4: CI/CD & Build Pipelines
- [x] Create `.github/workflows/build.yml` with:
  - Go: build + lint (golangci-lint) + test
  - Python: lint (ruff) + type check (mypy) + test (pytest)
  - TypeScript: lint (prettier) + type check + test (jest)
- [x] Configure pre-commit hooks:
  - `golangci-lint run` for Go
  - `ruff check --fix` for Python
  - `prettier --write` for TypeScript/JSON
- [x] Create `docker-compose.test.yml` for integration tests
- [x] Document build process in CONTRIBUTING.md

**Dependencies:** M2.1, M2.2, M2.3  
**Verification:**
- GitHub Actions workflow passes for all services
- Pre-commit hooks run without errors
- `docker-compose -f docker-compose.test.yml up` completes successfully

---

## M3: Core Event Pipeline

**Status:** � IN PROGRESS  
**Focus:** Ingestion, deduplication, LLM extraction

### Milestones

#### M3.1: Aggregator - MCP Host Implementation
- [x] Implement MCP discovery protocol (tools/list endpoint)
- [x] Create agentic scheduler for polling frequency
- [x] Implement Kafka producer with:
  - Retry logic (3 retries with exponential backoff)
  - Batching (100 events or 1s timeout)
  - Prometheus metrics (ingest_rate, validation_failures)
- [x] Add schema validation at edge (Pydantic call to Python sidecar)
- [x] Create comprehensive unit tests (>80% coverage)
- [x] Document MCP server setup guide

**Dependencies:** M2.1, M2.4  
**Verification:**
- MCP discovery returns list of available tools
- Kafka producer sends >1000 events/sec
- Schema violations rejected with clear error messages
- Prometheus metrics populated correctly

---

#### M3.2: Redis Deduplication Layer
- [x] Implement SHA-256 content hashing
- [x] Create sliding window dedup logic (24h TTL)
- [x] Write Redis Lua scripts for atomic check-set
- [x] Add RediSearch blocking queries
- [x] Create comprehensive unit tests (>80% coverage)

**Dependencies:** M1.3, M2.2  
**Verification:**
- Hash collisions handled correctly ✅
- TTL expiry works as expected ✅
- Botnet dedup clusters duplicates correctly ✅
- Lua script atomicity verified under concurrency ✅

---

#### M3.3: LLM Entity Extraction
- [x] Implement instructor-based LLM prompt
- [x] Create Pydantic STIX 2.1 models (Person, Org, Malware, etc.)
- [x] Implement Ollama fallback logic
- [x] Add confidence scoring for extracted entities
- [x] Implement rate limiting (tokens/sec)
- [x] Create comprehensive unit tests (>80% coverage)

**Dependencies:** M2.2, M3.1  
**Verification:**
- Entity extraction produces valid STIX objects
- Confidence scores correlate with accuracy
- Fallback to Ollama works on OpenAI failure
- Rate limiting prevents token exhaustion

---

#### M3.4: Processor Kafka Consumer
- [x] Implement consumer group pattern (multiple workers)
- [x] Create dead-letter queue (DLQ) for schema violations
- [x] Build processing pipeline: hash check → extract → resolve
- [x] Add Prometheus metrics:
  - Processing latency per event
  - Extraction accuracy (confidence distribution)
  - DLQ error rate
- [x] Create comprehensive integration tests

**Dependencies:** M3.1, M3.2, M3.3, M2.2  
**Verification:**
- Consumer group rebalances correctly
- Schema violations land in DLQ with error details
- Processing pipeline handles 1000+ events/sec
- All metrics populated correctly

---

## M4: Knowledge Graph Construction

**Status:** 🔴 NOT STARTED  
**Focus:** Entity resolution, graph persistence, GraphRAG indexing

### Milestones

#### M4.1: Entity Resolution Service
- [ ] Implement vector blocking (Qdrant semantic search)
- [ ] Implement graph structural matching (neighborhood analysis)
- [ ] Create merge logic:
  - Auto-merge on >95% confidence
  - Ambiguity alerts for 50-95% confidence
  - Rejection for <50% confidence
- [ ] Track entity lifecycle (creation, updates, SAME_AS relationships)
- [ ] Monitor false-positive rate
- [ ] Create comprehensive unit + integration tests

**Dependencies:** M2.2, M1.3 (Qdrant profile)  
**Verification:**
- Semantic search returns correct candidates
- Structural matching identifies relationships
- Merge logic produces correct entities
- False-positive rate <5%

---

#### M4.2: Neo4j Graph Persistence
- [ ] Create Neo4j schema:
  - Nodes: Person, Organization, Malware, Location, Campaign, AttackPattern
  - Properties: STIX-compliant fields + custom_properties
  - Edges: attributed-to, targets, uses, located-at, related-to
- [ ] Create indexes on:
  - Entity IDs (unique constraint)
  - Created/updated timestamps
  - Confidence scores
- [ ] Implement APOC procedures for community detection (Leiden/Louvain)
- [ ] Add transaction management + rollback on write failures
- [ ] Create comprehensive integration tests

**Dependencies:** M1.3 (Neo4j), M4.1  
**Verification:**
- Schema validates STIX compliance
- Indexes created successfully
- Community detection completes <10s for 10k nodes
- Transactions roll back on errors

---

#### M4.3: GraphRAG Indexing
- [ ] Implement community detection on subgraph updates
- [ ] Create natural language summary generation (LLM-based)
- [ ] Store summaries in Neo4j node properties
- [ ] Implement incremental updates (avoid full recalculation)
- [ ] Add Prometheus metrics:
  - Community detection latency
  - Summary generation time
  - Update frequency
- [ ] Create comprehensive tests

**Dependencies:** M4.2, M3.3  
**Verification:**
- Community detection produces coherent clusters
- Summaries are human-readable
- Incremental updates complete <5s
- All metrics within SLA

---

## M5: Delivery & Real-Time Alerting

**Status:** 🔴 NOT STARTED  
**Focus:** WebSocket gateway, interactive dashboard, audio briefings

### Milestones

#### M5.1: Kafka → WebSocket Gateway
- [ ] Subscribe to `analyst-alerts` Kafka topic
- [ ] Broadcast to connected WebSocket clients (Socket.io)
- [ ] Route alerts by tenant/subscription
- [ ] Implement connection pooling + heartbeat
- [ ] Add Prometheus metrics:
  - Connected clients count
  - Message broadcast latency
  - Connection lifecycle events
- [ ] Create comprehensive tests

**Dependencies:** M1.3 (Kafka), M2.3  
**Verification:**
- WebSocket connections maintain heartbeat
- Alerts broadcast to correct clients
- <2s latency from Kafka → browser
- Metrics populated correctly

---

#### M5.2: Interactive Graph Dashboard
- [ ] Implement Sigma.js WebGL rendering (support 100k+ nodes)
- [ ] Create force-directed layout algorithm
- [ ] Implement semantic zooming (aggregate → individual)
- [ ] Create Focus+Context filtering
- [ ] Add real-time node/edge highlighting on alerts
- [ ] Performance optimization:
  - Render 50k nodes in <500ms
  - Update on-demand (lazy loading)
  - GPU acceleration where available
- [ ] Create performance benchmarks

**Dependencies:** M5.1, M2.3, M4.2  
**Verification:**
- Dashboard loads 10k nodes smoothly
- Zoom/pan operations are responsive
- Real-time alerts highlight correctly
- Performance benchmarks met

---

#### M5.3: Audio Briefing Pipeline
- [ ] Create GraphRAG → briefing script generation
- [ ] Implement Kokoro TTS synthesis (fallback: ElevenLabs API)
- [ ] Store audio files in MinIO
- [ ] Schedule briefings:
  - Daily summary at 08:00 user timezone
  - On-demand alerts
- [ ] Generate secure signed URLs for download
- [ ] Create comprehensive tests

**Dependencies:** M4.3, M1.3 (MinIO), M2.2  
**Verification:**
- Briefing scripts are grammatically correct
- TTS produces clear, understandable audio
- Audio files stored + downloaded successfully
- Scheduling works as expected

---

## M6: Security, Multi-Tenancy & Polish

**Status:** 🔴 NOT STARTED  
**Focus:** Data isolation, plugin sandboxing, audit trail, production hardening

### Milestones

#### M6.1: Multi-Tenant Data Isolation
- [ ] Implement Neo4j Label-Based Access Control (LBAC)
- [ ] Redis key namespacing per tenant
- [ ] Query filtering middleware (inject tenant context)
- [ ] Implement federated queries for super-users
- [ ] Create cross-tenant leakage scenario tests
- [ ] Document multi-tenancy architecture

**Dependencies:** M4.2, M2.2  
**Verification:**
- Tenant A cannot query Tenant B data
- Federated queries return correct cross-tenant results
- All scenario tests pass

---

#### M6.2: Plugin Sandboxing
- [ ] Deploy MCP servers in gVisor microVMs (or Firecracker)
- [ ] Implement network policies (whitelist-only outbound)
- [ ] Set resource limits (CPU, memory, file descriptors)
- [ ] Validate output (reject malformed payloads)
- [ ] Create audit logging (all plugin invocations)
- [ ] Document sandboxing architecture

**Dependencies:** M3.1  
**Verification:**
- Plugin crashes don't crash Aggregator
- Network policies enforced correctly
- Resource limits respected
- Audit logs capture all events

---

#### M6.3: STIX 2.1 Compliance & Audit Trail
- [ ] Map all graph nodes to STIX Domain Objects (SDOs)
- [ ] Add `created_by_ref` to every node (plugin + analyst ID)
- [ ] Implement TAXII server for inter-agency sharing
- [ ] Create immutable audit log for all mutations
- [ ] Export capabilities:
  - STIX bundles
  - TAXII feeds
  - CSV/JSON reports
- [ ] Document compliance procedures

**Dependencies:** M4.2, M6.1  
**Verification:**
- All nodes have STIX mappings
- Audit log is immutable + timestamped
- TAXII server shares data correctly
- Exports validate against STIX schema

---

#### M6.4: Observability & Alerting
- [ ] Create Prometheus dashboards:
  - Kafka lag per consumer group
  - Neo4j write latency percentiles
  - LLM token usage + cost
  - Memory/CPU per service
- [ ] Create Grafana per-service dashboards
- [ ] Implement Loki JSON structured logging (all services)
- [ ] Define alert rules:
  - High DLQ rate (>1% of events)
  - Entity resolution failures (>5% false positives)
  - Plugin timeouts (>3 per hour)
  - Memory usage (>85% of limit)
- [ ] Document observability runbook

**Dependencies:** M1.3, M2.1, M2.2, M2.3  
**Verification:**
- All dashboards populated with real data
- Alert rules trigger on defined thresholds
- Logs are searchable + filterable
- Runbook covers common scenarios

---

#### M6.5: Documentation & Onboarding
- [ ] Create API documentation:
  - OpenAPI 3.1 specs (auto-generated)
  - Example requests/responses
  - Error codes + troubleshooting
- [ ] Create plugin development guide:
  - MCP server template
  - Step-by-step tutorial
  - Best practices
- [ ] Create operational runbook:
  - Service startup/shutdown
  - Troubleshooting guide
  - Backup/recovery procedures
  - Scaling guidelines
- [ ] Create user guide:
  - Dashboard navigation
  - Briefing subscriptions
  - Search syntax
  - FAQ

**Dependencies:** M6.1, M6.2, M6.3, M6.4  
**Verification:**
- Documentation is complete + accurate
- Examples are copy-paste ready
- Links verified (no 404s)
- User feedback positive

---

#### M6.6: Integration Testing & Performance Tuning
- [ ] Create end-to-end tests:
  - Raw event → ingestion → graph → alert → UI
  - Multi-step workflows
  - Error recovery scenarios
- [ ] Load testing:
  - 10k events/sec for 5 minutes
  - Sustained latency <5s per event
  - Memory/CPU profiling
  - No message loss verification
- [ ] Performance tuning:
  - Optimize hot paths (caching, indexes)
  - Batch writes where possible
  - Query plan analysis
- [ ] Create performance baseline + SLAs

**Dependencies:** All previous milestones  
**Verification:**
- End-to-end tests pass consistently
- 10k EPS sustained without degradation
- Memory stays within 8 GB budget
- All SLAs met under load

---

## Dependencies Graph

```
M1.1 → M1.2
       ↓
M1.3 ← M1.2
   ↓   ↓
M1.4 M1.3 → M1.5
   ↓   ↓
M2.1 M2.2 M2.3 ← M1.5
      ↓    ↓    ↓
      M2.4 ← M2.1
      ↓
M3.1 ← M2.1
   ↓
M3.2 ← M1.3
   ↓
M3.3 ← M3.1
   ↓
M3.4 ← M3.1, M3.2, M3.3
   ↓
M4.1 ← M3.4
   ↓
M4.2 ← M4.1
   ↓
M4.3 ← M4.2
   ↓
M5.1 ← M3.4
   ↓
M5.2 ← M5.1, M4.2
   ↓
M5.3 ← M4.3
   ↓
M6.1 ← M4.2
   ↓
M6.2 ← M3.1
   ↓
M6.3 ← M4.2, M6.1
   ↓
M6.4 ← M6.3
   ↓
M6.5 ← M6.4
   ↓
M6.6 ← All previous
```

---

## Parallel Work Opportunities

- M2.1 (Aggregator) can be built in parallel with M2.2 (Processor)
- M3.2 (Redis) can be built in parallel with M3.1 (Aggregator MCP)
- M3.3 (LLM) can be built in parallel with M3.1, M3.2
- M5.1 (WebSocket) can start after M1.3 (Kafka), before M4 completion
- M6.1, M6.2, M6.3 can be built in parallel after M4 foundation complete

---

## Success Criteria Summary

| Milestone | Key Success Metric |
|-----------|-------------------|
| M1 | Docker Compose runs, docs complete |
| M2 | All services build + health checks pass |
| M3 | 1000+ events/sec through pipeline, <500ms latency |
| M4 | 10k nodes in graph, community detection <10s |
| M5 | <2s latency from alert to UI, audio briefings work |
| M6 | 10k EPS sustained, no multi-tenant leakage, <5s E2E latency |

---

## Questions for Stakeholders

1. **Plugin Priority:** Which MCP plugins should be built first? (Suggest: Twitter, Shodan, corporate registry scrapers)
2. **LLM Provider:** Stick with Ollama for Phase 1-2, or integrate cloud provider (OpenAI, Gemini)?
3. **Multi-Tenancy:** Is it needed in Phase 1, or defer to Phase 6?
4. **Sandboxing:** Start with Docker network isolation (Phase 1), or implement gVisor immediately (Phase 1)?
5. **UI/UX:** Are there specific dashboard requirements beyond Sigma.js rendering?

---

## Review Cadence

- **Weekly standups** during active development phases
- **Bi-weekly reviews** of completed milestones
- **Bi-monthly planning** for next 2-3 milestones

---

## Document Owners

| Document | Owner | Last Review |
|----------|-------|------------|
| IMPLEMENTATION-PLAN.md | Architecture Lead | May 16, 2026 |
| ROADMAP.md | Project Lead | May 16, 2026 |
| Copilot Instructions | Dev Lead | Pending |
| Agent Contexts | Dev Lead | Pending |
