# Omni-G Implementation Plan

**Project Status:** Phase 1 - Foundation & Infrastructure  
**Last Updated:** May 16, 2026  
**Repository:** github.com/yourusername/omni-g

## Overview

This document outlines the complete 6-phase implementation strategy for Omni-G—a distributed, event-driven Knowledge Graph platform for the Intelligence Community. The plan spans from infrastructure setup through security hardening and production deployment.

## Phase 1: Foundation & Infrastructure ✅ IN PROGRESS

**Duration:** 1-2 weeks  
**Objective:** Set up Docker, Kubernetes skeleton, Git, and local service orchestration.  
**Deliverables:** Infrastructure-as-Code, service scaffolding, CI/CD foundation

### Tasks

#### 1.1 Git Repository & Version Control
- **Status:** ✅ Complete
- Initialize bare Git repository with proper .gitignore for Python, Node.js, Go
- Configure pre-commit hooks directory (.githooks)
- Add CONTRIBUTING.md and CODE_OF_CONDUCT.md templates
- Reference: [awesome-copilot CONTRIBUTING](https://github.com/github/awesome-copilot/blob/main/CONTRIBUTING.md)

#### 1.2 Directory Structure
- **Status:** ✅ Complete
- Create `/services/{aggregator, processor, delivery}` microservice roots
- Create `/mcp-plugins` for isolated MCP server implementations
- Create `/infrastructure/{docker-compose, k8s, configs}` for IaC
- Create `/docs/{IMPLEMENTATION-PLAN, ROADMAP, agent-contexts}`
- Each service gets `/cmd`, `/src`, `/internal` structure per language conventions

#### 1.3 Docker Compose Multi-Profile Setup
- **Status:** ✅ Complete
- **File:** `infrastructure/docker-compose.yml`
- **Profiles:**
  - `core`: Kafka (KRaft), Redis Stack, Neo4j Community — **minimum required for local dev**
  - `vector`: Qdrant vector DB + embedding services
  - `ai`: Ollama (local LLM) + Kokoro TTS
  - `observability`: Prometheus, Grafana, Loki
  - `storage`: MinIO S3-compatible object storage
  - `services`: Aggregator, Processor, Delivery microservices
  - `all`: Everything (resource-intensive; not recommended on 8 GB machine)

- **Resource Constraints:**
  - Neo4j: heap=2GB, pagecache=512MB
  - Redis: 1GB max
  - Kafka: 1GB broker memory
  - Ollama: GPU optional, CPU mode supported
  - Total baseline (core): ~5GB at startup

- **Health Checks:** All services include readiness probes for orchestration

#### 1.4 Environment Configuration
- **Status:** In Progress
- Create `.env.example` template with all service endpoints
- Create `infrastructure/.env.local` gitignored with actual secrets
- Document environment variables per service

#### 1.5 Copilot Instructions & Agent Framework
- **Status:** In Progress
- Create `.copilot-instructions.md` (architecture validation mode)
- Create `development-instructions.md` (hands-on coding guidance)
- Create `AGENTS.md` (agent definitions and invocation patterns)
- Create `/docs/agent-contexts/{architect, developer, service-specialist, devops}.md`
- Reference: [awesome-copilot structure](https://github.com/github/awesome-copilot)

---

## Phase 2: Service Scaffolding (Planned)

**Duration:** 1-2 weeks  
**Objective:** Scaffold each microservice with build pipelines and internal APIs.  
**Deliverables:** Service stubs, CI/CD workflows, unit test frameworks

### Key Tasks
- Initialize Go module for Aggregator (`go mod init`)
- Initialize Python project for Processor (`pyproject.toml`, uv config)
- Initialize Next.js for Delivery (`create-next-app`)
- Create Dockerfile for each service with multi-stage builds
- Create GitHub Actions build workflow (.github/workflows/build.yml)
- Add pre-commit hooks: golangci-lint, ruff, prettier
- Create integration test runner: `docker-compose up && npm run test:e2e`

### Verification Checklist
- ✅ `docker-compose --profile core up` runs without errors
- ✅ `npm run dev` starts Next.js dev server (Delivery)
- ✅ `go run ./cmd` starts Aggregator health endpoint
- ✅ `fastapi dev` starts Processor health endpoint
- ✅ Git commits are clean (pre-commit passes)

---

## Phase 3: Core Event Pipeline (Planned)

**Duration:** 2-3 weeks  
**Objective:** Implement ingestion → deduplication → extraction pipeline.  
**Deliverables:** MCP host implementation, Kafka producer/consumer, LLM integration

### Key Tasks
- **Aggregator:**
  - Implement MCP discovery (tools/list endpoint)
  - Agentic scheduler for polling frequency
  - Kafka producer with retry + batching logic
  - Schema validation at edge (Pydantic)
  - Prometheus metrics for ingest rate, validation failures

- **Redis Dedup Layer:**
  - SHA-256 content hashing
  - Sliding window botnet dedup (24h TTL)
  - Redis Lua scripts for atomic check-set

- **LLM Extraction:**
  - Instructor-based prompt engineering
  - Pydantic STIX 2.1 model output
  - Fallback to Ollama if OpenAI unavailable
  - Confidence scoring + rate limiting

- **Processor Kafka Consumer:**
  - Consumer group pattern (multi-worker)
  - Dead-letter queue (DLQ) for schema violations
  - Processing pipeline: hash → extract → resolve
  - Latency & accuracy metrics

### Verification Checklist
- ✅ Raw event injected → Kafka `raw-feed` topic
- ✅ Deduped in Redis with correct hash
- ✅ Extracted to STIX object with confidence score
- ✅ Invalid schema → DLQ with error details
- ✅ All pipeline steps logged with latency metrics

---

## Phase 4: Knowledge Graph Construction (Planned)

**Duration:** 2-3 weeks  
**Objective:** Entity resolution and graph persistence.  
**Deliverables:** Neo4j schema, entity resolution engine, GraphRAG indexing

### Key Tasks
- **Entity Resolution:**
  - Vector blocking: entity embeddings → Qdrant semantic search
  - Graph structural matching: neighborhood analysis
  - Merge logic: high-confidence (>95%) auto-merge, low-confidence → alerts
  - Entity lifecycle management + SAME_AS relationships
  - False-positive rate monitoring

- **Neo4j Graph Persistence:**
  - Schema: nodes (Person, Org, Malware, Location, Campaign, AttackPattern)
  - Edge types: attributed-to, targets, uses, located-at, etc.
  - Index strategy: entity IDs, timestamps, confidence scores
  - APOC procedures for community detection (Leiden/Louvain)
  - Transaction management + rollback on write failures

- **GraphRAG Indexing:**
  - Community detection on subgraph updates
  - Natural language summary generation per community
  - Incremental updates (avoid full graph recalculation)
  - Summary storage in Neo4j node properties

### Verification Checklist
- ✅ Graph query returns nodes + relationships
- ✅ Community detection runs without crashing
- ✅ Entity resolution merges duplicates correctly
- ✅ GraphRAG summaries are human-readable
- ✅ Incremental updates complete in <5s

---

## Phase 5: Delivery & Real-Time Alerting (Planned)

**Duration:** 2 weeks  
**Objective:** Deliver intelligence to analysts via multiple modalities.  
**Deliverables:** WebSocket gateway, interactive dashboard, audio briefings

### Key Tasks
- **Kafka → WebSocket Gateway:**
  - Subscribe to `analyst-alerts` topic
  - Broadcast to connected WebSocket clients (Socket.io)
  - Route alerts by tenant/subscription
  - Connection pooling + heartbeat management

- **Interactive Graph Dashboard:**
  - Sigma.js WebGL rendering (100k+ nodes)
  - Force-directed layout algorithm
  - Semantic zooming (aggregate → individual)
  - Focus+Context filtering
  - Real-time node/edge highlighting on alerts
  - Performance: 50k+ node render in <500ms

- **Audio Briefing Pipeline:**
  - GraphRAG → briefing script generation
  - Kokoro TTS synthesis (fallback: ElevenLabs)
  - Audio file storage in MinIO
  - Scheduling: daily briefing + on-demand alerts
  - Secure signed URLs for download

### Verification Checklist
- ✅ Dashboard loads 1000 nodes smoothly
- ✅ WebSocket receives alerts in real-time
- ✅ Audio file downloads without errors
- ✅ Briefing script is grammatically correct
- ✅ <2s latency from alert to UI update

---

## Phase 6: Security, Multi-Tenancy & Polish (Planned)

**Duration:** 2-3 weeks  
**Objective:** Production-grade security and governance.  
**Deliverables:** Multi-tenant isolation, plugin sandboxing, audit trail, observability

### Key Tasks
- **Multi-Tenant Data Isolation:**
  - Neo4j Label-Based Access Control (LBAC)
  - Redis key namespacing per tenant
  - Kafka topic segregation (optional)
  - Query filtering middleware
  - Cross-tenant leakage scenario tests

- **Plugin Sandboxing:**
  - Deploy MCP servers in gVisor microVMs or Firecracker
  - Network policies: whitelist-only outbound
  - Resource limits: CPU, memory, file descriptors
  - Output validation: malformed payload rejection
  - Audit logging: all plugin invocations

- **STIX 2.1 Compliance & Audit Trail:**
  - Map all nodes to STIX Domain Objects (SDOs)
  - `created_by_ref` on every node (plugin + analyst ID)
  - TAXII server for inter-agency sharing
  - Immutable audit log for all mutations
  - STIX bundle + TAXII feed exports

- **Observability & Alerting:**
  - Prometheus dashboards: Kafka lag, Neo4j latency, LLM tokens
  - Grafana per-service dashboards
  - Loki JSON structured logging
  - Alert rules: high DLQ rate, resolution failures, timeouts
  - Liveness + readiness probes for all services

- **Documentation & Onboarding:**
  - OpenAPI specs for each service
  - Plugin development guide + MCP templates
  - Operational runbook: troubleshooting, scaling, backups
  - User guide: dashboard, briefing subscriptions

- **Integration Testing & Performance:**
  - End-to-end: data → ingestion → graph → alert → UI
  - Load testing: 10k events/sec through pipeline
  - Latency SLAs: <5s raw→graph, <2s dashboard alert
  - Memory: verify 8 GB constraints on dev machine
  - Optimize hot paths: caching, indexes, batch writes

### Verification Checklist
- ✅ Tenant A cannot query Tenant B data
- ✅ Plugin crash doesn't crash Aggregator
- ✅ Audit log records all mutations with timestamps
- ✅ Observability dashboard shows all metrics
- ✅ 10k EPS sustained for 5 minutes with no message loss
- ✅ CPU/memory stay within 8 GB budget

---

## Cross-Cutting Concerns

### Testing Strategy
- **Unit Tests:** Each service maintains >70% code coverage
  - Go: testify + table-driven tests
  - Python: pytest + fixtures for Kafka/Redis/Neo4j
  - TypeScript: Jest + React Testing Library

- **Integration Tests:** Docker Compose orchestration
  - Full pipeline: raw event → graph → UI alert
  - Schema validation at each stage
  - Error handling + DLQ scenarios

- **Load Tests:** k6 or Apache JMeter
  - 10k events/sec for 5 minutes
  - Sustained latency <5s per event
  - Memory/CPU profiling on 8 GB machine

### Documentation
- **API Documentation:** OpenAPI 3.1 specs (auto-generated from FastAPI + Go)
- **Architecture Decision Records (ADRs):** docs/adr/ for design choices
- **Runbook:** docs/RUNBOOK.md for operational tasks
- **Security:** docs/SECURITY.md for threat model + mitigations

### DevOps & Deployment
- **Local Development:** Docker Compose with profiles
- **Staging:** Kubernetes (Phase 5+, optional)
- **Production:** Terraform + Helm charts (future)
- **CI/CD:** GitHub Actions (build → test → push)

---

## Resource Budget

### Development Machine (8 GB RAM, 100 GB SSD)

| Profile | Services | Memory | Disk |
|---------|----------|--------|------|
| `core` | Kafka, Redis, Neo4j | ~5 GB | ~10 GB |
| `+ vector` | Qdrant | +1 GB | +5 GB |
| `+ ai` | Ollama, Kokoro | +2-3 GB | +10 GB |
| `+ observability` | Prometheus, Grafana, Loki | +500 MB | ~2 GB |
| **Headroom** | OS + app services | ~500 MB | — |

**Recommendation:** Start with `--profile core` + `--profile ai`, add others as needed.

---

## Success Criteria

### Phase 1 ✅
- [ ] Docker Compose runs all core services without errors
- [ ] Git repository initialized with clean history
- [ ] All documentation files created (Plan, Roadmap, Instructions, Agents)
- [ ] Pre-commit hooks configured for all languages
- [ ] Environment variables documented

### Phase 2
- [ ] Each service builds and runs health check
- [ ] Unit tests pass with >70% coverage
- [ ] GitHub Actions build workflow succeeds
- [ ] Service-to-service communication tested

### Phase 3
- [ ] End-to-end: raw event → Kafka → dedup → extract → STIX
- [ ] Prometheus metrics populated
- [ ] DLQ captures schema violations
- [ ] Latency <500ms per event through pipeline

### Phase 4
- [ ] Graph queries return correct entities + relationships
- [ ] Entity resolution merges duplicates without false positives
- [ ] Community detection completes <10s
- [ ] GraphRAG summaries are coherent

### Phase 5
- [ ] Dashboard renders 10k nodes in <500ms
- [ ] WebSocket alerts reach UI in <2s
- [ ] Audio briefings download successfully
- [ ] Multiple concurrent users supported

### Phase 6
- [ ] Multi-tenant data completely isolated
- [ ] Plugin sandboxing prevents information leakage
- [ ] Audit trail captures all mutations
- [ ] 10k events/sec sustained with no message loss
- [ ] All SLAs met under load

---

## Timeline & Milestones

```
May 2026     |Jun|Jul|Aug|Sep|Oct|
Phase 1  ###
Phase 2         ###
Phase 3             ###
Phase 4                 ###
Phase 5                     ###
Phase 6                         ###
```

**Total:** ~12 weeks for full implementation + hardening

---

## Next Steps

1. ✅ **Now:** Review this plan with stakeholders
2. **Next:** Begin Phase 1 - run `docker-compose --profile core up`
3. **Then:** Phase 2 - scaffold services with build pipelines
4. **Continue:** Follow Phase 3-6 in sequence, validating at each milestone

---

## Questions & Decisions

**Q: Should plugins self-register or use static registry?**  
A: Start with static registry in `.env`, evolve to dynamic service discovery (Consul/Etcd) in Phase 5+.

**Q: How strict should STIX ontology mapping be?**  
A: Enforce core types (Person, Malware, Location), allow custom properties via `custom_properties` field.

**Q: Ollama or cloud LLM?**  
A: Ollama for Phase 1-3 (free, local), integrate cloud provider abstraction in Phase 5 for production.

**Q: Firecracker/gVisor in Phase 1 or Phase 6?**  
A: Phase 1 uses Docker network isolation, Phase 6 upgrades to kernel-level sandboxing.

---

## Contacts & Resources

- **Project Lead:** [Your Name]
- **Architecture Docs:** [Link to Architecture & Business.md]
- **Tech Stack Reference:** [Link to techstack.md]
- **awesome-copilot:** https://github.com/github/awesome-copilot
- **GraphRAG:** https://microsoft.github.io/graphrag/
- **MCP Protocol:** https://modelcontextprotocol.io/
