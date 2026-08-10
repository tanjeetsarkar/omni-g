# ProcessingPipeline.process() — Deep Dive

This document explains every line of logic inside the `process()` method defined in
[`src/processor/pipeline.py`](src/processor/pipeline.py). The method is the single entry point
through which every Kafka message flows from raw JSON to persisted Knowledge Graph nodes,
community summaries, and real-time analyst alerts.

---

## Table of Contents

1. [Function Signature and Return Values](#1-function-signature-and-return-values)
2. [How the Pipeline is Wired Up](#2-how-the-pipeline-is-wired-up)
3. [Cross-Cutting Concern: StageEventPublisher](#3-cross-cutting-concern-stageeventpublisher)
4. [Step 1 — Schema Validation](#4-step-1--schema-validation)
5. [Step 2 — Deduplication](#5-step-2--deduplication)
6. [Step 3 — LLM Entity Extraction](#6-step-3--llm-entity-extraction)
7. [Step 3.5 — Grounding Validation](#7-step-35--grounding-validation)
8. [Step 4 — Entity Resolution](#8-step-4--entity-resolution)
9. [Step 5 — Graph Persistence](#9-step-5--graph-persistence)
10. [Step 6 — GraphRAG Incremental Indexing](#10-step-6--graphrag-incremental-indexing)
11. [Step 7 — Alert Publishing](#11-step-7--alert-publishing)
12. [Return Value and Final Logging](#12-return-value-and-final-logging)
13. [Data Models Glossary](#13-data-models-glossary)
14. [Prometheus Metrics Reference](#14-prometheus-metrics-reference)
15. [Error Handling Summary](#15-error-handling-summary)

---

## 1. Function Signature and Return Values

```python
async def process(self, event: dict[str, Any]) -> ExtractionResult | None:
```

**Input:** A raw Python dictionary deserialized from a Kafka message. This dictionary has not
been validated yet when it enters — it may contain any JSON content published by any MCP plugin
to the `raw-feed` Kafka topic.

**Return values:**

| Return value | Meaning |
|---|---|
| `ExtractionResult` | Event was processed end-to-end successfully. Contains all extracted entities, relationships, and a confidence score. |
| `None` | Event was silently dropped because it is a duplicate of something already processed within the deduplication TTL window. |

**Raises:**

| Exception | Meaning |
|---|---|
| `SchemaViolationError` | Event envelope failed Pydantic validation. The Kafka consumer catches this and routes the message to the Dead Letter Queue (DLQ). |

The pipeline is entirely `async` — every blocking I/O call (Redis, Neo4j, Qdrant, LLM HTTP) is
awaited and never blocks the asyncio event loop.

---

## 2. How the Pipeline is Wired Up

`ProcessingPipeline` is constructed once at service startup via dependency injection. Not all
stages are mandatory:

```python
class ProcessingPipeline:
    def __init__(
        self,
        deduplicator: ContentDeduplicator,      # required — always runs
        zeromem_extractor: ZeroMemExtractor,    # required — always runs
        resolver: EntityResolver | None = None, # optional — skipped if None
        graph_persistence: GraphPersistenceService | None = None,  # optional
        graphrag_indexer: GraphRAGIndexer | None = None,           # optional
        alert_publisher: AlertPublisher | None = None,             # optional
        stage_publisher: StageEventPublisher | None = None,        # optional
    ) -> None:
```

The deduplicator and extractor are always wired. The optional stages can be disabled entirely
(for testing, development, or lightweight deployments) by passing `None`. Each optional stage
is guarded by `if self._X is not None:` before executing.

---

## 3. Cross-Cutting Concern: StageEventPublisher

Before and after every stage, the pipeline calls `self._stage_publisher.publish(...)` if one
is wired. This is not part of the processing logic — it is purely instrumentation for the UI.

```python
# Example from schema_validation stage:
if self._stage_publisher:
    self._stage_publisher.publish(
        event.get("id", ""),
        event.get("tenant_id", "default"),
        "schema_validation",
        "active",   # signals: stage has started
    )
# ... do the actual work ...
if self._stage_publisher:
    self._stage_publisher.publish(
        envelope.id, envelope.tenant_id, "schema_validation", "done"
    )
```

**What `StageEventPublisher.publish()` does:**

It constructs a `StageEvent` Pydantic model and immediately serializes it to JSON and sends it
to a Kafka topic (default: `processor-events`) using a synchronous `KafkaProducer` (from the
`kafka-python-ng` library). The `send()` call is non-blocking — it enqueues the message in
a background thread.

```python
class StageEvent(BaseModel):
    event_id: str
    tenant_id: str
    stage: str
    status: Literal["active", "done"]
    timestamp: datetime
```

The Delivery service's WebSocket gateway subscribes to `processor-events` and broadcasts these
events to connected browser clients. This is how the UI knows which pipeline stage is currently
running for a given event in real time.

**Critical design detail:** `StageEventPublisher.publish()` wraps its entire body in a
`try/except` and **never re-raises exceptions**. Stage instrumentation failing must never
interrupt the processing pipeline.

---

## 4. Step 1 — Schema Validation

**Purpose:** Reject any structurally malformed events before they pollute downstream systems.

### What happens

```python
try:
    envelope = RawEventEnvelope.model_validate(event)
except PydanticValidationError as exc:
    SCHEMA_VIOLATIONS.inc()
    logger.warning("pipeline_schema_validation_failed", ...)
    raise SchemaViolationError(str(exc)) from exc
```

Pydantic tries to parse the raw `dict` into a `RawEventEnvelope` object. If it fails, the
`PydanticValidationError` is caught, the `processor_schema_violations_total` Prometheus counter
is incremented, and a `SchemaViolationError` is raised. The Kafka consumer layer catches this
specific exception type and routes the original message to the DLQ with metadata about the
error.

### RawEventEnvelope schema

```python
class RawEventEnvelope(BaseModel):
    id: str = ""
    source: str = ""
    tenant_id: str = "default"
    plugin_name: str | None = None
    plugin_version: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "allow"}   # <-- extra keys from the plugin are kept

    @model_validator(mode="after")
    def validate_payload(self) -> RawEventEnvelope:
        if not self.payload:
            raise ValueError("payload must not be empty")
        required_keys = {"text", "content", "data", "url"}
        if not required_keys.intersection(self.payload.keys()):
            raise ValueError("payload must contain at least one of: text, content, data, url")
        for k, v in self.payload.items():
            if v is None or v == "":
                raise ValueError(f"payload.{k} must not be None or empty string")
        return self
```

**Three rules enforced:**

1. `payload` dict must not be empty (a plugin must send some content).
2. At least one of `text`, `content`, `data`, or `url` must appear in `payload` (the pipeline
   needs something to extract from).
3. No key inside `payload` may have a `None` or empty-string value (partial data is rejected
   hard).

The `extra = "allow"` config means any additional fields the plugin sends (timestamps, URLs,
raw HTML, etc.) are passed through without error and remain accessible on the envelope object.

### After this step

The raw `dict` is now a typed `RawEventEnvelope`. Downstream code uses `envelope.id`,
`envelope.tenant_id`, `envelope.payload`, etc. The `tenant_id` defaults to `"default"` if the
plugin did not supply one, ensuring every event belongs to some tenant.

---

## 5. Step 2 — Deduplication

**Purpose:** Drop events whose content has already been processed within the TTL window.
This prevents duplicate entities being written to Neo4j when a plugin republishes the same
article or feed item.

### The hash function

```python
def _hash_event(event: dict[str, Any]) -> str:
    """Return the SHA-256 hex digest of the canonical sorted-key JSON of *event*."""
    canonical = json.dumps(event, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

Before touching Redis, the deduplicator serializes the **entire original raw event dict** to
JSON with `sort_keys=True`. This means the hash is key-order independent — two dicts with the
same content but different key order produce the same hash. The SHA-256 hex string (64 chars)
becomes the fingerprint.

### Redis key format

```
dedup:{tenant_id}:{sha256hex}
```

The `tenant_id` prefix ensures that the same content published by two different tenants is
treated as two distinct events (multi-tenant isolation).

### The Lua atomic check-and-set

The deduplication check-and-set is intentionally atomic. A non-atomic EXISTS followed by SET
would have a TOCTOU race condition under high concurrency. The Lua script runs atomically on
the Redis server:

```lua
local key = KEYS[1]
local ttl = tonumber(ARGV[1])
local exists = redis.call('EXISTS', key)
if exists == 1 then
    redis.call('EXPIRE', key, ttl)   -- sliding window: refresh TTL on re-seen event
    return 'duplicate'
else
    redis.call('SET', key, '1', 'EX', ttl)
    return 'new'
end
```

This script is loaded via `SCRIPT LOAD` at startup, getting a SHA back. At call time
`EVALSHA <sha> 1 <key> <ttl>` executes it. If Redis was restarted and flushed the script cache,
the code falls back to `EVAL` with the full script text, then re-registers it.

**Sliding window TTL:** If the same event arrives again before the window expires, the existing
key's TTL is refreshed to the full TTL. This prevents a flood of re-posts from ever sneaking
through near the TTL boundary.

**Default TTL:** 86400 seconds (24 hours). Configurable via the `ContentDeduplicator` constructor.

### Fail-open design

```python
except ConnectionError:
    return DedupResult(is_duplicate=False, content_hash=content_hash, event_id=event_id)
except ResponseError:
    return DedupResult(is_duplicate=False, content_hash=content_hash, event_id=event_id)
```

If Redis is unavailable or returns an error, the deduplicator returns `is_duplicate=False`
(treating the event as new). This means a Redis outage causes duplicate processing rather than
a total pipeline halt. Duplicates entering Neo4j are handled gracefully by `MERGE` (idempotent
upsert) in the graph persistence layer.

### Outcome in the pipeline

```python
if dedup_result.is_duplicate:
    DEDUP_DROPS.labels(tenant_id=envelope.tenant_id).inc()
    logger.info("pipeline_duplicate_event_dropped", ...)
    return None
```

If the event is a duplicate, `process()` returns `None` immediately. The Kafka consumer
acknowledges the message (it is not an error — it was intentionally dropped) and moves to the
next message.

---

## 6. Step 3 — LLM Entity Extraction

**Purpose:** Use a local LLM to read the event text and extract structured entities and
relationships. This is the most computationally expensive step.

### Text extraction from payload

```python
text: str = str(envelope.payload.get("text") or envelope.payload.get("content", ""))
metadata: dict[str, Any] = {
    "plugin_name": envelope.plugin_name,
    "plugin_version": envelope.plugin_version,
    "source_type": envelope.payload.get("source_type", "general"),
}
```

The pipeline prefers `payload["text"]` over `payload["content"]`. If `text` is falsy (empty
string, `None`), it falls back to `content`. The `source_type` field drives which system prompt
is selected for the LLM.

### Rate limiting

`ZeroMemExtractor` contains an `asyncio.Semaphore(LLM_RATE_LIMIT_RPS)` (default: 10). The
`extract()` call is wrapped in `async with self._semaphore:`, which means at most
`LLM_RATE_LIMIT_RPS` concurrent LLM calls are running at once. This prevents flooding the
local Ollama server.

### System prompt selection

The prompt is chosen by `source_type`:

| source_type | Prompt used |
|---|---|
| `general` | `SYSTEM_PROMPT_GENERAL` — broad OSINT analyst, all intelligence domains |
| `news` | `SYSTEM_PROMPT_NEWS` — news articles, RSS feeds, current events focus |
| `biographical` | `SYSTEM_PROMPT_BIOGRAPHICAL` — Wikipedia, Wikidata, person/org reference content |
| `wikidata` | Also `SYSTEM_PROMPT_BIOGRAPHICAL` |
| `threat_intel` | `SYSTEM_PROMPT_THREAT_INTEL` — threat actors, malware, IOCs |
| anything else | Falls back to `SYSTEM_PROMPT_GENERAL` |

Every prompt is suffixed with `ID_BINDING_INSTRUCTIONS`, which provides:
- A rule requiring every entity to have a unique temporary `id` field (e.g. `"id-1"`, `"id-2"`).
- A rule that `source_ref` and `target_ref` in relationships must match those temporary IDs.
- **Critical source grounding rules**: the LLM is explicitly instructed to only extract
  entities that appear verbatim in the source text, and to include a `source_span` field (the
  exact excerpt from the text that names the entity).
- A JSON few-shot example showing the expected output structure.

### PydanticAI agent call

```python
agent = Agent(
    self._primary_model,
    system_prompt=system_prompt,
    output_type=_LLMEntities,   # Pydantic model — structured output
    retries=3,
)
run_res = await agent.run(text)
result = run_res.output
```

`pydantic-ai` wraps the Ollama/OpenAI-compatible HTTP API and enforces that the LLM response
is valid JSON matching `_LLMEntities`. It retries up to 3 times if the output does not
validate. The LLM URL points to a local Ollama instance by default (`http://localhost:11434/v1`).

### Primary → Fallback → Empty result chain

```python
try:
    return await self._call_primary(text, source_type)
except Exception as exc:
    logger.warning("llm_primary_failed", ...)
    try:
        return await self._call_fallback(text, source_type)
    except Exception as exc2:
        logger.error("llm_fallback_failed", ...)
        return _LLMEntities()   # empty — no entities, no relationships
```

If the primary model (default: `qwen2.5:1.5b`) fails for any reason (timeout, model error,
JSON parse failure), the extractor immediately tries the fallback model (default: `qwen2.5:3b`).
If the fallback also fails, it returns an empty `_LLMEntities()` object. This means the pipeline
**never raises from the extraction stage** — it degrades gracefully to an empty result. An empty
extraction results in `extraction_confidence = 0.0`, and the alert publishing step at Step 7
only fires for `confidence > 0.5`, so a failed extraction silently produces no alert.

### Internal LLM data models

The LLM is asked to produce `_LLMEntities`:

```python
class _LLMEntity(BaseModel):
    id: str | None = None        # LLM's temp cross-ref (e.g. "id-1")
    type: str = "Unknown"        # free-form: "Person", "Organization", etc.
    name: str = "Unknown"
    description: str | None = None
    confidence: float | None = None
    properties: dict[str, Any] = {}
    source_span: str | None = None   # verbatim excerpt from source text

class _LLMRelationship(BaseModel):
    type: str = "RELATED_TO"
    source_ref: str = ""         # must match an entity's id field
    target_ref: str = ""
    confidence: float | None = None
```

### ID normalization

The LLM's temporary IDs (`"id-1"`, `"id-2"`) are cross-reference markers. After extraction,
`_normalize_llm_entities()` replaces them with real UUIDs:

```python
def _make_id(llm_id: str | None) -> str:
    entity_id = f"entity--{uuid4()}"
    if llm_id:
        id_map[llm_id] = entity_id   # record mapping temp → real UUID
    return entity_id
```

Relationships are resolved by looking up `source_ref` and `target_ref` in `id_map`. If a
reference cannot be resolved (e.g. the LLM hallucinated a reference to a non-existent entity
ID), the relationship is silently dropped.

Relationship types are normalized to UPPER_SNAKE_CASE:
```python
rel_type = re.sub(r"[^a-zA-Z0-9_]", "_", r.type).upper()
# e.g. "related-to" → "RELATED_TO", "works for" → "WORKS_FOR"
```

### Confidence calculation

After normalization, a confidence score for the whole extraction is computed:

```python
def _calculate_confidence(self, entities: _LLMEntities, source_type: str) -> float:
    total = len(entities.entities)
    if total == 0:
        return 0.0
    types = {e.type for e in entities.entities if e.type and e.type != "Unknown"}
    diversity = len(types)
    base = min(1.0, total * 0.1 + diversity * 0.05)
    boost = 0.1 if source_type in ("biographical", "wikidata") else 0.0
    return min(1.0, base + boost)
```

The formula rewards:
- **Quantity**: each extracted entity contributes `+0.1` to the base score.
- **Diversity**: each unique entity type (excluding `"Unknown"`) contributes an additional
  `+0.05`.
- **Source authority**: biographical and wikidata sources get a `+0.1` boost because their
  facts are explicitly asserted.

Examples:
- 0 entities → confidence `0.0`
- 3 entities, all same type → `3 * 0.1 + 1 * 0.05 = 0.35`
- 5 entities, 3 different types, biographical source → `min(1.0, 5*0.1 + 3*0.05 + 0.1) = 0.75`

This score is stored in `ExtractionResult.extraction_confidence` and is what drives the alert
publishing threshold check in Step 7.

---

## 7. Step 3.5 — Grounding Validation

**Purpose:** Act as a second line of defense against LLM hallucinations. Even if the LLM
followed the source grounding instructions in the prompt, this step verifies each extracted
entity actually appears in the raw source text before allowing it into the Knowledge Graph.

The step number "3.5" is intentional in the code comments — it was inserted between the LLM
extraction and entity resolution steps after the fact.

### Entity grounding check

```python
def _is_entity_grounded(entity: Entity, source_text: str) -> bool:
    if not source_text:
        return True  # Cannot validate without source text; pass through

    # Preferred: check LLM-supplied evidence spans
    for span in entity.source_spans:
        if span.text and span.text.lower() in source_text.lower():
            return True

    # Fallback: case-insensitive name match
    name = (entity.name or "").strip()
    if name.lower() in ("", "unknown"):
        return False
    return name.lower() in source_text.lower()
```

**Two-tier check:**

1. **LLM evidence spans (preferred):** If the LLM populated `source_span` (which becomes
   `entity.source_spans[0].text`), the pipeline checks whether that verbatim excerpt actually
   appears in the source text (case-insensitive). If it does, the entity is grounded.

2. **Name fallback:** If no evidence spans are present, or none matched, the pipeline does a
   simple case-insensitive substring check: is the entity's `name` anywhere in the source text?
   Entities with name `""` or `"Unknown"` are always rejected at this fallback stage.

**Empty source text pass-through:** If the event's `text` field was empty (e.g. the payload
only had a `url`), `source_text` is `""`. In this case, all entities are passed through without
grounding checks — there is simply no text to verify against.

### Relationship pruning

If an entity is rejected, every relationship that touches it (as either source or target) is
also dropped:

```python
rejected_entity_ids: set[str] = set()
# ... fill rejected_entity_ids during entity loop ...

grounded_relationships = [
    r
    for r in extraction.relationships
    if r.source_ref not in rejected_entity_ids
    and r.target_ref not in rejected_entity_ids
]
```

This ensures the graph never contains a relationship with a dangling endpoint.

### Immutable update pattern

```python
extraction = extraction.model_copy(
    update={"entities": grounded_entities, "relationships": grounded_relationships}
)
```

`ExtractionResult` is a Pydantic model. Pydantic's `model_copy(update=...)` returns a new
object with the specified fields overwritten — the original is not mutated. All downstream
steps receive the post-grounding extraction.

### Metrics

Two labeled counters track rejected artifacts:
```
processor_grounding_rejections_total{tenant_id=..., reason="not_in_source"}
processor_grounding_rejections_total{tenant_id=..., reason="endpoint_not_grounded"}
```

---

## 8. Step 4 — Entity Resolution

**Purpose:** Before writing an entity to Neo4j, check whether a matching entity already exists
in the graph. If so, merge them rather than creating duplicates. This is the step that keeps the
Knowledge Graph clean and deduplicated at the entity level (distinct from message-level
deduplication in Step 2).

This step is entirely skipped if `self._resolver is None`.

### What resolve_and_persist does

```python
await self._resolver.resolve_and_persist(envelope.tenant_id, entity)
```

This is a convenience wrapper that calls `resolve()` then `persist_entity()` sequentially. It
runs once per entity in the grounded extraction list.

### Stage 1 — Vector blocking via Qdrant

```python
text = f"{entity.type} {entity.name}"   # e.g. "Person Narendra Modi"
vector = await self._embed(text)
```

The entity's type and name are concatenated into a short text string, which is then embedded
using the `nomic-embed-text` model via Ollama (768-dimensional float vectors by default).

The vector is **upserted** into Qdrant (collection: `entities_{tenant_id}`) so that the entity
is immediately available for future resolution queries. Then a similarity search returns the
top-5 nearest neighbors (excluding the entity itself):

```python
raw = await self._qdrant.search(
    collection_name=collection,
    query_vector=vector,
    limit=5,
)
```

Each result becomes a `CandidateMatch(entity_id=..., score=..., match_type="vector")`.

**Embedding fallback:** If the Ollama embedding call fails, a deterministic SHA-256-based
placeholder vector is generated from the entity text. This means vector blocking still works
in offline/test environments — it will produce lower-quality matches but never crashes.

### Stage 2 — Graph structural matching via Neo4j

Three independent Neo4j queries run to find candidates the vector search may have missed:

**Query 1: Exact name / alias match (score = 1.0)**
```cypher
MATCH (e)
WHERE e.tenant_id = $tenant_id
  AND e.type = $entity_type
  AND e.id <> $entity_id
  AND (
    e.name = $name
    OR $name IN coalesce(e.aliases, [])
  )
RETURN e.id AS entity_id, 1.0 AS score
```
If the incoming entity's name is an exact match (or an alias) of an existing node of the same
type in the same tenant, it gets score 1.0 — the maximum possible — and will trigger an
AUTO_MERGE decision.

**Query 2: Co-occurrence (score = shared_count / 10.0)**
```cypher
MATCH (existing)-[]->(shared)<-[]-(other {id: $entity_id})
WHERE existing.tenant_id = $tenant_id
  AND existing.id <> $entity_id
WITH existing, count(DISTINCT shared) AS cnt
WHERE cnt >= 2
RETURN existing.id AS entity_id,
       toFloat(cnt) / 10.0 AS score
```
Two entities that share two or more common relationship targets are likely the same real-world
entity. For example, if "PM Modi" and "Narendra Modi" both have `VISITED` edges to "Washington
D.C." and "Paris", that's strong evidence they are the same person. Score = shared_count / 10,
capped at 1.0.

**Query 3: Fuzzy name match via Neo4j pre-filter + Python rapidfuzz**

A two-step approach to avoid a full graph scan:

Step A — Neo4j pre-filter: fetch all entities of the same type where the name contains the
last token of the incoming entity name (e.g. for "Narendra Modi", use "Modi" as the anchor):
```cypher
MATCH (e:Entity)
WHERE e.tenant_id = $tenant_id
  AND e.type = $entity_type
  AND e.id <> $entity_id
  AND toLower(e.name) CONTAINS toLower($last_token)
RETURN e.id AS entity_id, e.name AS name, coalesce(e.aliases, []) AS aliases
LIMIT 200
```

Step B — Python scoring: for each candidate, compute `fuzz.WRatio(incoming_name, candidate_name)`
and also `fuzz.WRatio(incoming_name, alias)` for every alias. Take the max. If the max score
≥ `FUZZY_NAME_MATCH_THRESHOLD` (default: 85 on a 0–100 scale), add the candidate with score
`best_score / 100.0`.

`fuzz.WRatio` is RapidFuzz's "Weighted Ratio" — it tries multiple fuzzy matching strategies
(partial ratio, token set ratio, etc.) and returns the best. This correctly handles cases like
"PM Modi" vs "Narendra Modi" where the names are not identical but clearly refer to the same person.

### Merge decision logic

All candidates from vector blocking and structural matching are pooled. For the same entity ID,
only the highest score from any source is kept:

```python
best: dict[str, float] = {}
for c in candidates:
    if c.entity_id not in best or c.score > best[c.entity_id]:
        best[c.entity_id] = c.score
```

Then the top-scoring candidate is evaluated against thresholds:

| Score | Decision | What happens |
|---|---|---|
| ≥ 0.95 (`AUTO_MERGE_THRESHOLD`) | `AUTO_MERGE` | Incoming entity's properties are merged into the existing node. The existing node's ID is used going forward. |
| 0.50–0.95 (`AMBIGUOUS_THRESHOLD`) | `AMBIGUOUS` | A new node is created AND a `SAME_AS` edge is written linking it to the matched entity. A Prometheus counter tracks these as analyst-review candidates. |
| < 0.50 | `NEW_ENTITY` | A new entity node is created with no link to any existing entity. |
| No candidates | `NEW_ENTITY` | No existing entity found; create fresh. |

**Neo4j SAME_AS edge for AMBIGUOUS:**
```python
await self._create_same_as(
    source_id=new_id,
    target_id=resolution.matched_entity_id,
    tenant_id=tenant_id,
    confidence=resolution.confidence_score,
)
```
This creates an edge `(new_entity)-[:SAME_AS {confidence: X}]->(matched_entity)` that analysts
can review and either confirm (merge) or reject (remove).

---

## 9. Step 5 — Graph Persistence

**Purpose:** Write all grounded (and resolved) entities and relationships from the extraction
to Neo4j in a single atomic transaction.

This step is skipped if `self._graph_persistence is None`.

### The persist_extraction transaction

```python
await self._graph_persistence.persist_extraction(extraction, envelope.tenant_id)
```

Inside `persist_extraction`, a single Neo4j session and transaction are opened:

```python
async with self._driver.session() as session:
    async with await session.begin_transaction() as tx:
        # all entity writes
        # all relationship writes
        # if ANY write fails: entire tx rolls back automatically
```

**Entity node MERGE:**

```cypher
MERGE (n:Entity:{type_label}:{tenant_label} {id: $id})
ON CREATE SET n += $props
ON MATCH SET n.modified = $modified,
             n.name = $name,
             n.confidence = $confidence,
             n.description = $description,
             n.properties = $properties_json,
             n.tenant_id = $tenant_id,
             n.source_id = $source_id
RETURN n.id AS entity_id
```

Where `{type_label}` and `{tenant_label}` are the sanitized Neo4j label versions of
`entity.type` and `tenant_id`. For example: an entity of type `"Person"` in tenant
`"default"` gets labels `Entity:Person:default`.

`MERGE` is idempotent — if the node already exists (same `id`), only the listed `ON MATCH`
properties are updated. If it does not exist, all properties are set via `ON CREATE SET n += $props`.

The `_props_from_entity()` function flattens the `Entity` model into Neo4j-compatible types:
- `str`, `int`, `float`, `bool`, `None` → stored as-is
- `datetime` → ISO-8601 string
- Lists/dicts → JSON-encoded string, **except** `aliases` which is stored as a native Neo4j list
  (so Cypher's `$name IN e.aliases` list membership query works correctly)

**Relationship edge MERGE:**

```cypher
MATCH (src:Entity {id: $source_id}),
      (tgt:Entity {id: $target_id})
WHERE src.tenant_id = $tenant_id
  AND tgt.tenant_id = $tenant_id
MERGE (src)-[r:{edge_type}]->(tgt)
SET r.id = $rel_id,
    r.tenant_id = $tenant_id,
    r.confidence = $confidence,
    r.created = $created,
    r.modified = $modified
```

The `WHERE src.tenant_id = $tenant_id AND tgt.tenant_id = $tenant_id` clause enforces
cross-tenant isolation at the database level — an edge can never connect entities from
different tenants.

**Relationship type mapping:**

Known STIX relationship types are mapped to Neo4j edge labels. Unknown types are normalized
by upper-casing and replacing non-alphanumeric characters with underscores:

```python
_REL_TYPE_MAP = {
    "attributed-to": "ATTRIBUTED_TO",
    "targets": "TARGETS",
    "uses": "USES",
    "located-at": "LOCATED_AT",
    "related-to": "RELATED_TO",
}

def _map_relationship_type(stix_rel_type: str) -> str:
    if stix_rel_type in _REL_TYPE_MAP:
        return _REL_TYPE_MAP[stix_rel_type]
    return re.sub(r"[^a-zA-Z0-9_]", "_", stix_rel_type).upper()
```

Since the LLM can emit any UPPER_SNAKE_CASE relationship type, the normalization covers cases
like `"WORKS_FOR"`, `"PARTICIPATED_IN"`, `"ACQUIRED"`, etc. natively.

**Atomic rollback:** If any single entity write or relationship write fails, the
`async with ... begin_transaction()` context manager rolls back all writes from this event.
Neo4j is left in its pre-event state. The exception propagates up to the Kafka consumer, which
retries the message.

---

## 10. Step 6 — GraphRAG Incremental Indexing

**Purpose:** After new entities land in Neo4j, update the community structure and regenerate
LLM summaries for the affected neighborhood. This is what enables the Delivery service to
answer global-level synthesis questions like "what are the main clusters of activity this week?"

This step is skipped if `self._graphrag_indexer is None`.

### Per-entity incremental index

```python
for entity_id in [e.id for e in extraction.entities]:
    await self._graphrag_indexer.index_incremental(entity_id, envelope.tenant_id)
```

Every entity in the extraction is indexed independently. Each call runs community detection on
the **2-hop subgraph** around that entity.

### What index_incremental does

**Step A: Fetch the 2-hop neighborhood from Neo4j**

```cypher
MATCH (origin:Entity {id: $entity_id, tenant_id: $tenant_id})
      -[*1..2]-(neighbor:Entity {tenant_id: $tenant_id})
RETURN DISTINCT neighbor.id AS nid
```

This traverses up to 2 relationship hops from the entity in any direction (undirected traversal)
and collects all neighbor entity IDs within the same tenant. These form the subgraph to analyze.

**Step B: Fetch edges within the subgraph**

```cypher
MATCH (a:Entity {tenant_id: $tenant_id})
      -[r]-(b:Entity {tenant_id: $tenant_id})
WHERE a.id IN $ids AND b.id IN $ids
RETURN a.id AS source_id, b.id AS target_id
```

All relationship edges between nodes in the subgraph are retrieved. If the entity is isolated
(no edges), a self-loop `[(entity_id, entity_id)]` is used to ensure it is still assigned a
community.

**Step C: Connected-components community detection (Python)**

For incremental indexing, the code always uses Python-side Union-Find connected-components
(not GDS) because it is fast enough for small subgraphs:

```python
def _connected_components(edges: list[tuple[str, str]]) -> dict[str, int]:
    # Union-Find algorithm
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        if x not in parent:
            parent[x] = x
        if parent[x] != x:
            parent[x] = find(parent[x])   # path compression
        return parent[x]

    def union(a: str, b: str) -> None:
        pa, pb = find(a), find(b)
        if pa != pb:
            parent[pa] = pb

    for src, tgt in edges:
        union(src, tgt)
    ...
```

This groups the subgraph nodes into connected components, assigning each component a
0-based integer community ID.

For full re-indexing (triggered externally via the `/graphrag/trigger` endpoint), the code
first tries the GDS (Graph Data Science) plugin:
- `gds.leiden.stream` (default) — Leiden algorithm, a refinement of Louvain
- `gds.louvain.stream` (fallback)

If GDS is not installed, it falls back to the Python connected-components approach for the
full graph as well.

**Step D: Summarize communities with LLM**

```python
summaries_generated = await self._summarize_and_store(communities, tenant_id)
```

For each detected community, an LLM generates a natural-language summary of the cluster. The
summary is stored directly as a property on each entity node in Neo4j:

```cypher
MATCH (n:Entity {tenant_id: $tenant_id})
WHERE n.community_id IS NOT NULL
RETURN n.community_id, n.community_summary, count(n) AS entity_count
```

These summaries are later retrieved by the Delivery service to answer synthesis questions about
communities without re-querying the LLM at query time.

---

## 11. Step 7 — Alert Publishing

**Purpose:** Notify analysts in real time that significant entities have been extracted and
persisted. Only high-confidence extractions trigger an alert, preventing notification fatigue
from low-quality or hallucinated extractions.

This step is skipped entirely if `self._alert_publisher is None`.

### Confidence gate

```python
if self._alert_publisher is not None and extraction.extraction_confidence > 0.5:
```

Only extractions with confidence above 0.5 publish an alert. Recall from Step 3 that
confidence 0.5 requires at least 5 entities (or fewer with type diversity). An empty extraction
(0 entities) has confidence 0.0 and never triggers an alert.

### Summary text construction

```python
if hasattr(extraction, "summary_text"):
    summary_text = str(getattr(extraction, "summary_text", ""))[:500]
else:
    n = len(extraction.entities)
    summary_text = f"{n} {'entity' if n == 1 else 'entities'} extracted"
```

If the `ExtractionResult` has a `summary_text` attribute set (possible in future extension),
use that (truncated to 500 chars). Otherwise, the summary is a simple entity count string like
`"7 entities extracted"`. This is a minimal summary — the LLM-generated community summaries
from Step 6 are the richer synthesis output.

### AnalystAlert model

```python
class AnalystAlert(BaseModel):
    alert_id: str = Field(default_factory=lambda: str(uuid4()))  # fresh UUID per alert
    tenant_id: str
    entity_ids: list[str]      # IDs of all entities extracted in this event
    community_id: str | None = None
    summary: str               # text summary
    confidence: float          # extraction_confidence score
    timestamp: datetime        # UTC time of alert creation
    source_event_id: str       # the original Kafka event ID
```

### Kafka publish

```python
await self._alert_publisher.publish(alert)
```

Inside `AlertPublisher.publish()`:

```python
payload = json.loads(alert.model_dump_json())
self._producer.send(self._topic, payload)   # topic: "analyst-alerts"
```

The alert is serialized to JSON and sent to the `analyst-alerts` Kafka topic using a
`KafkaProducer` from `kafka-python-ng`. The `send()` call is non-blocking — it enqueues the
message in a background thread. The Delivery service's WebSocket gateway subscribes to
`analyst-alerts` and broadcasts the alert to connected browser clients in real time.

Unlike `StageEventPublisher`, errors in `AlertPublisher.publish()` **do raise** — a failed
alert is a real error worth reporting and potentially retrying.

---

## 12. Return Value and Final Logging

```python
if self._stage_publisher:
    self._stage_publisher.publish(
        envelope.id, envelope.tenant_id, "pipeline_complete", "done"
    )
logger.info(
    "pipeline_run_done",
    extra={
        "event_id": envelope.id,
        "tenant_id": envelope.tenant_id,
        "confidence": extraction.extraction_confidence,
    },
)
return extraction
```

The pipeline fires a final `pipeline_complete` stage event so the UI can mark the event
as fully processed. The structured log record includes the final extraction confidence for
observability dashboards. Then the `ExtractionResult` is returned to the Kafka consumer, which
commits the Kafka offset for this message.

---

## 13. Data Models Glossary

### EvidenceSpan
```python
class EvidenceSpan(BaseModel):
    text: str    # verbatim excerpt from source text naming the entity
    start: int   # best-effort character offset (start)
    end: int     # best-effort character offset (end)
```
Supplied by the LLM as `source_span`, used by the grounding validation gate.

### Entity
```python
class Entity(BaseModel):
    id: str              # "entity--{uuid4}"
    type: str            # free-form: "Person", "Organization", "Event", etc.
    name: str
    description: str | None
    properties: dict[str, Any]  # domain-specific: aliases, sectors, country, ...
    confidence: float    # 0.0–1.0, per-entity score from LLM
    tenant_id: str       # set by pipeline from envelope; empty at extraction time
    source_id: str | None
    source_spans: list[EvidenceSpan]
    created: datetime
    modified: datetime
```
The open-ended `type` field is what makes this system domain-agnostic. The LLM assigns whatever
type makes sense from context — there is no fixed ontology.

### Relationship
```python
class Relationship(BaseModel):
    id: str              # "relationship--{uuid4}"
    type: str            # UPPER_SNAKE_CASE: "KNOWS", "LOCATED_AT", "PARTICIPATED_IN", etc.
    source_ref: str      # entity id
    target_ref: str      # entity id
    confidence: float    # 0.0–1.0
    tenant_id: str
    created: datetime
    modified: datetime
```

### ExtractionResult
```python
class ExtractionResult(BaseModel):
    source_event_id: str
    entities: list[Entity]
    relationships: list[Relationship]
    extraction_confidence: float    # 0.0–1.0, computed from entity count + diversity
    plugin_id: str | None
    plugin_version: str | None
```

---

## 14. Prometheus Metrics Reference

These metrics are emitted by the pipeline and visible in Grafana:

| Metric | Type | Labels | Description |
|---|---|---|---|
| `processor_extraction_confidence` | Histogram | — | Distribution of LLM extraction confidence scores |
| `processor_schema_violations_total` | Counter | — | Events rejected at schema validation |
| `processor_dedup_drops_total` | Counter | `tenant_id` | Events dropped as duplicates |
| `processor_pipeline_stage_duration_seconds` | Histogram | `stage` | Time per pipeline stage |
| `processor_grounding_rejections_total` | Counter | `tenant_id`, `reason` | Entities rejected by grounding gate |
| `processor_resolution_decisions_total` | Counter | `decision`, `tenant_id` | Entity resolution outcomes |
| `processor_resolution_latency_seconds` | Histogram | `tenant_id` | End-to-end entity resolution latency |
| `processor_false_positive_alerts_total` | Counter | `tenant_id` | AMBIGUOUS decisions (analyst review) |
| `processor_same_as_merges_total` | Counter | `tenant_id` | AUTO_MERGE decisions |
| `processor_graph_write_latency_seconds` | Histogram | `operation` | Neo4j write latency |
| `processor_graph_write_errors_total` | Counter | `operation` | Neo4j write failures |
| `processor_alerts_published_total` | Counter | `tenant_id` | Analyst alerts sent to Kafka |
| `processor_alert_publish_errors_total` | Counter | — | Alert publish failures |
| `processor_graphrag_index_latency_seconds` | Histogram | `tenant_id`, `mode` | GraphRAG indexing latency |
| `processor_graphrag_communities_total` | Gauge | `tenant_id` | Community count after last indexing run |
| `processor_graphrag_summaries_updated_total` | Counter | `tenant_id` | Community summaries written |

Stage names used in `processor_pipeline_stage_duration_seconds`:
`schema_validation`, `deduplication`, `llm_extraction`, `grounding_validation`,
`entity_resolution`, `graph_persistence`, `graphrag_index`, `alert_publishing`

---

## 15. Error Handling Summary

| Stage | Error type | What happens |
|---|---|---|
| Schema validation | `PydanticValidationError` | → `SchemaViolationError` → Kafka consumer routes to DLQ |
| Deduplication | `redis.ConnectionError` / `ResponseError` | Fail-open: event treated as new, processing continues |
| LLM extraction (primary) | Any exception | Log warning, try fallback model |
| LLM extraction (fallback) | Any exception | Log error, return empty `_LLMEntities`, pipeline continues with 0 entities |
| Grounding validation | No exceptions raised | Ungrounded entities silently dropped, metrics incremented |
| Entity resolution (Qdrant embedding) | Any exception | Fall back to deterministic SHA-256-based vector |
| Entity resolution (fuzzy match) | Any exception | Log warning, return empty fuzzy candidates list |
| Graph persistence | Any exception | Neo4j transaction rolls back, exception propagates → Kafka consumer retries |
| GraphRAG indexing (GDS) | Any exception | Fall back to Python connected-components |
| Alert publishing | Any exception | Log error, re-raise (consumer may retry or DLQ) |
| Stage publisher | Any exception | Swallowed silently — instrumentation never interrupts pipeline |
