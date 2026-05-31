# Architectural Revamp: STIX Extraction via Pydantic AI & Asynchronous Ollama Embeddings

## 1. Architectural Flaws in Current Setup

### Underpowered LLM Core & JSON Extraction Failures
Operating under strict hardware constraints (maximum model size of `qwen2.5:3b`) creates severe structural failures inside standard zero-shot extraction:
- **Reference Binding Failures:** Small models fail to maintain structural matches between an entity's internal ID array and the `source_ref`/`target_ref` values inside relationship blocks. This leads to invalid refs or `null` values which break Pydantic validation.
- **Null Value Rejection:** Models output `null` instead of non-nullable empty strings (`""`) or default placeholders, causing `Instructor` to fail validation on critical fields.
- **Blind Retries:** Under the current `instructor` setup, when validation fails, the system either crashes or runs arbitrary retries without feeding concrete error tracebacks back into the model to help it learn.

### Non-Semantic Vector Invalidation
- **Deterministic SHA-256 Hashing:** The embedding method (`_embed` inside `resolver.py`) uses an iterative SHA-256 binary hash mapped to a 768-dimensional float array. It is computationally fast but completely non-semantic.
- **Match Invalidation:** As a result, Qdrant functions strictly as an exact-match helper rather than a semantic match platform. Similar entities with minor typos or alternate naming conventions fail to cluster in vector space.

### Ambiguity SAME_AS Node Explosion
- **Merged Node Inflation:** Any candidate evaluated within the `0.50` to `0.95` confidence range is saved as a new standalone node linked via a `SAME_AS` edge.
- **Cycle Bloat:** Over time, these groupings accumulate cyclic linkages rather than converging onto single, rich canonical STIX identities.

---

## 2. Industry-Standard Open-Source Reference Architecture

### OpenCTI (Open Cyber Threat Intelligence)
- **Principle:** Enforces strong decoupling between raw intake scraped events and structured STIX 2.1 schemas.
- **Workflow:** Standardizes all extracted items into a verified STIX Bundle at the ingestion edge before injecting them into relational graph layers (PostgreSQL and Neo4j).

### Microsoft GraphRAG (Structured Document Inferences)
- **Principle:** Uses hierarchical prompt orchestration to dynamically summarize granular entities, clusters, and communities.
- **Workflow:** Relies on robust self-correction logic and few-shot templates to enforce structure across low-parameter local models.

---

## 3. Implementation Plan: High-Precision Pydantic AI Ingestion

```
  +----------------------+
  | Raw Ingested Event   |
  +----------------------+
             |
             v
  +--------------------------------------------------------+
  |              PydanticAI Client                         |
  |  - System Prompts with strict ID Binding rules         |
  |  - In-Context Few-Shot structure examples              |
  +--------------------------------------------------------+
             |
      [Schema Check] ──── (Invalid JSON / Corrupted Ref)
             |                      |
             |                      v
             |           +-------------------------------+
             |           |   Self-Correction Loop        |
             |           | - Intercept Pydantic trace    |
             |           | - Feed traceback to LLM       |
             |           +-------------------------------+
             |                      |
             +<---------------------+
             |
      (Validation Passes)
             |
             v
  +--------------------------------------------------------+
  |             _normalize_llm_entities()                  |
  | - Map temporary IDs (id-1, id-2) to STIX UUIDs         |
  +--------------------------------------------------------+
             |
             v
  +--------------------------------------------------------+
  |           Asynchronous Ollama Embedding                 |
  | - Call 'nomic-embed-text' via httpx Client             |
  +--------------------------------------------------------+
             |
             v
  +----------------------+
  |  Qdrant Candidate    |
  |  Blocking            |
  +----------------------+
```

### Phase 1: Overhaul to Pydantic AI Ingestion Core
- **Dependencies:** Add `pydantic-ai[logfire]` to `services/processor/pyproject.toml`.
- **System Prompt Overhaul (`prompts.py`):** Write strict instructions detailing the structural requirements of entity ID binding. Instruct the LLM to construct simple local temporary IDs (e.g., `id-1`, `id-2`) and mandate that all relationships must link to these exact IDs.
- **Few-Shot Injector (`prompts.py`):** Include a compact, multi-entity structured JSON template mapping two entities (a Threat Actor and a Location) alongside an explicit, structurally linked relationship.
- **PydanticAI Agent Migration (`extractor.py`):** Deprecate `instructor` in favor of a declarative `Agent(model='openai:qwen2.5:3b', result_type=_LLMEntities)` instance.
- **Active Retries & Traceback Recovery:** Leverage PydanticAI's multi-turn validation retry loop. When a schema violation occurs, capture the traceback text and feed it directly back to the LLM to cleanly repair its structure in-situ.

### Phase 2: Async Local Semantic Filtering (Qdrant & Ollama)
- **Ollama Integration:** Deprecate the mock SHA-256 block-vector constructor in `services/processor/src/resolution/resolver.py#L536`.
- **Asynchronous Embeddings:** Convert `_embed(text)` to an `async def _embed_async(text)` method. Use `httpx.AsyncClient` inside the resolver to securely post embedding requests to Ollama's local `nomic-embed-text` endpoint (`http://localhost:11434/api/embeddings`).
- **Enriched Search Context:** Embed a detailed metadata representation instead of only type/name, such as: `f"{entity.type} {entity.name}: {entity.description or ''}"`.

---

## 4. Technical Extension for docs/ROADMAP.md

To be appended directly to the project roadmap file immediately before Milestone 6.

```markdown
## Milestone 5.4: High-Fidelity Extraction & PydanticAI Migration

**Status:** 🔴 PLANNED (Pre-M6)
**Focus:** Structured JSON recovery, self-correcting ingestion, local semantic search.

### Deliverables
- [ ] **M5.4.1: PydanticAI Library Migration**
  - Integrate PydanticAI into the Processor workspace (`pyproject.toml`).
  - Deprecate the existing `instructor` call pattern in `extractor.py`.
  - Wrap extraction with PydanticAI's `Agent` using structured `result_type=_LLMEntities`.
- [ ] **M5.4.2: Self-Correcting LLM Ingestion Layer**
  - Enable PydanticAI's multi-turn schema correction loop (max 3 retries).
  - Intercept extraction failures and feed validation traceback contexts back to `qwen2.5:3b`.
  - Overhaul `prompts.py` to establish binding syntax patterns (mapping temporary IDs like `id-1` to relationship targets) using concrete, compact few-shot examples.
- [ ] **M5.4.3: Ollama Semantic Embedding Core**
  - Deprecate dummy SHA-256 block-vector generator in `resolver.py`.
  - Implement an asynchronous Ollama embedding client calling `nomic-embed-text` (768-D).
  - Enrich Qdrant search payload by embedding detailed meta-attributes: `f"{type} {name}: {description}"`.

### Dependencies
- M3.4 (LLM integration base) must be completed.
- Qdrant (`core` and `vector` Docker profiles) must be running.

### Verification
- `pytest tests/test_extractor.py` shows 100% resolution of corrupted schema responses.
- Qdrant similarity searches evaluate on semantic distance (cosine) rather than exact substring matches.
- Logging confirms schema issues are repaired live in under 2 retry cycles.
```
