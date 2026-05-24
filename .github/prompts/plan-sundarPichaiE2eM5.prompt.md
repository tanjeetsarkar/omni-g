# Plan: E2E Real Data Test — "Sundar Pichai" → Milestone 5 (v2)

## TL;DR
5 phases covering (1) STIX extraction prompt registry for general intelligence, (2) 4 open-source MCP plugins (Wikipedia, Wikidata, Google News RSS, Reuters RSS), (3) Aggregator on-demand search endpoint, (4) search-first homepage UX with real-time pipeline progress, and (5) live Neo4j visualization — enabling "Sundar Pichai" to flow end-to-end and render as a live knowledge graph.

**Data Flow:**
```
Home page (search bar "Sundar Pichai")
  → POST /api/search → Aggregator POST /search
  → Wikipedia + Wikidata + GoogleNews + Reuters plugins (tools/call)
  → Kafka raw-feed → Processor
  → Per-entity STIX prompt extraction (Identity, Location, Campaign…)
  → Entity resolution → Neo4j + GraphRAG summaries
  → analyst-alerts → WebSocket → "pipeline done" signal
  → Dashboard fetches real Neo4j /api/graph → Sigma.js visualization
```

---

## Phase 1 — STIX Extraction Prompt Registry
*Before building plugins — the extractor must handle general intelligence, not just threat intel*

### Step 1 — Create `services/processor/src/llm/prompts.py` (new file)

A `PromptRegistry` class with named, versioned prompts for each STIX entity type. System prompt defines the analyst role and output contract; per-entity guidance is embedded as few-shot examples in the user message prefix.

**`SYSTEM_PROMPT_GENERAL`:**
```
You are a STIX 2.1 Open-Source Intelligence (OSINT) analyst. Your task is to
extract ALL entities and relationships from the text and return them as structured
JSON matching the ExtractionResult schema. You must handle all intelligence domains:
people, organizations, geopolitics, business, technology, and cybersecurity.

Entity extraction rules:
- Identity (individual): full name, aliases, roles/titles, nationality, sector
- Identity (organization): name, type (company/govt/NGO), sectors, country
- Location: city, country, region — extract every geographic mention
- ThreatActor: adversarial groups or individuals with malicious intent
- Malware: malicious software, ransomware, spyware families
- Campaign: coordinated initiatives — product launches, operations, programs
- AttackPattern: TTPs, methods, techniques described in the text
- Indicator: observable artifacts — IPs, hashes, domains, email addresses
Relationship rules:
- Use STIX SRO types: attributed-to, targets, uses, located-at, related-to
- Extract ALL implied relationships, not just explicit ones
- Assign confidence 0-1 per relationship based on assertion strength
```

Additional context-specific prompts:
- `SYSTEM_PROMPT_BIOGRAPHICAL` — for Wikipedia/people content (emphasizes Identity, Location, relationships)
- `SYSTEM_PROMPT_NEWS` — for news articles (emphasizes Events, Campaigns, updated roles)
- `SYSTEM_PROMPT_THREAT_INTEL` — existing threat-intel focus (preserves current behavior)

Expose `get_prompt(source_type: str) -> str` where `source_type` is passed via `metadata["source_type"]` in the event payload. Sources: `"biographical"`, `"news"`, `"threat_intel"`, `"general"` (default).

### Step 2 — Update `services/processor/src/llm/extractor.py`
- Replace `_SYSTEM_PRIMARY` constant with `PromptRegistry.get_prompt(metadata.get("source_type", "general"))`
- `_SYSTEM_FALLBACK` → `PromptRegistry.SYSTEM_PROMPT_FALLBACK` (keep simple)
- Pass `source_type` from `metadata` into `_call_primary()` and `_call_fallback()`
- `_calculate_confidence()`: add a small boost (0.1) for `source_type in ("biographical", "wikidata")` since these are authoritative structured sources

### Step 3 — `prompts.py` architecture for upgradeability
- Keep all prompts in one file with clear `# Version:` comments per prompt
- A dict `_PROMPT_VERSIONS: dict[str, list[str]]` enables A/B testing in future
- No external config or DB needed — prompts are code, upgraded via git

---

## Phase 2 — OSINT MCP Plugins (4 plugins)
*All 4 plugins follow the exact `mcp-plugins/echo/main.go` pattern*

### Step 4 — `mcp-plugins/wikipedia/` (Go)
- **Tool:** `fetch_wikipedia_article(query: string)`
- Calls: `GET https://en.wikipedia.org/api/rest_v1/page/summary/{url-encoded-query}` → summary + extract
- Also: `GET https://en.wikipedia.org/w/api.php?action=query&prop=extracts&titles={query}&format=json` for full intro text
- Returns 2 SSE content blocks: title+summary, full extract
- Metadata: `source_type=biographical`
- Port 8091

### Step 5 — `mcp-plugins/wikidata/` (Go)
- **Tool:** `fetch_wikidata_facts(query: string)`
- Calls: Wikidata SPARQL endpoint `https://query.wikidata.org/sparql` with query that finds entity by label and returns: employer, position held, education, birthplace, nationality, country of citizenship, notable works
- Returns 1 SSE block: structured fact list as `"WIKIDATA FACTS:\nemployer: Google\nposition: CEO\n..."`
- Metadata: `source_type=biographical`
- Port 8092
- *Why Wikidata*: provides explicit structured relationship facts (A is employer of B) that directly map to STIX relationships — much higher extraction accuracy than free text

### Step 6 — `mcp-plugins/newsrss/` (Go)
- **Tool:** `search_news(query: string)`
- Fetches Google News RSS: `https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en`
- Parses RSS 2.0 XML, returns top 10 items, 1 block per item: `"NEWS: {title}\n{description}\nSOURCE: {link}"`
- Metadata: `source_type=news`
- Port 8093

### Step 7 — `mcp-plugins/reuters/` (Go)
- **Tool:** `fetch_reuters_rss(query: string)`
- Fetches Reuters Technology RSS: `https://feeds.reuters.com/reuters/technologyNews` (filter by query substring in article text)
- Returns matching items as content blocks
- Fallback: AP News RSS `https://rsshub.app/apnews/topics/technology`
- Metadata: `source_type=news`
- Port 8094

*New files per plugin:* `main.go`, `go.mod`, `Dockerfile`

---

## Phase 3 — Aggregator On-Demand Search Endpoint
*Depends on Phase 2*

### Step 8 — `services/aggregator/internal/server/search_handler.go` (new)
- `POST /search` body: `{"query": "Sundar Pichai", "sources": ["wikipedia","wikidata","newsrss","reuters"]}`
- Generates `search_id = uuid.New()`
- For each matched plugin, calls `client.CallTool(ctx, toolName, map[string]any{"query": query})`
- Each ContentBlock → `pipeline.Process(ctx, block, pluginURL)` — adds `source_type` to metadata
- Returns `{"search_id": uuid, "events_queued": N}` with HTTP 202
- Reuses: `mcp.Client.CallTool()`, `pipeline.Pipeline.Process()`, loop pattern from `scheduler.go`

### Step 9 — Wire in `server.go` + `main.go`
- Register `POST /search` in `services/aggregator/internal/server/server.go`
- Initialize `SearchHandler` with plugin-client map + pipeline in `services/aggregator/cmd/aggregator/main.go`

---

## Phase 4 — Search-First UX with Pipeline Progress
*Depends on Phase 3 + Phase 5 (Neo4j graph API)*

**New UX flow:**
```
[Home page] Search bar only → Submit
  → [Processing view, inline on home page] Pipeline stage updates in real-time
    Stage 1: Fetching open sources… (Wikipedia, Wikidata, News)
    Stage 2: Publishing to pipeline…
    Stage 3: Extracting entities with AI…
    Stage 4: Resolving & writing to Knowledge Graph…
    Stage 5: Building community summaries…
  → On WebSocket "alert" event for this query's entities → "Data ready!"
  → Auto-navigate to /dashboard?q={query}
```

### Step 10 — Redesign `services/delivery/src/app/page.tsx` (home page)
- Replace current title + "Open Dashboard" button with a centered search interface:
  - `<h1>Omni-G</h1>`, subtitle, large `<input>` + Search button
  - On submit → calls `POST /api/search`, stores `search_id` in component state
  - Transitions inline to `<PipelineProgress>` component

### Step 11 — New `services/delivery/src/components/PipelineProgress.tsx`
- Shows 5 ordered stages with status icons (pending / active / done / error):
  1. *Fetching open sources* — immediately `active` on search start, `done` after 202 response
  2. *Processing events* — `active` after 3s
  3. *Extracting entities with AI* — `active` after 8s
  4. *Writing to Knowledge Graph* — `active` after 15s
  5. *Building community insights* — `active` after 22s
- Uses time-based simulation (not real Kafka stage events — avoids pipeline instrumentation for M5)
- WebSocket listener via `useAlertHighlight` hook — when an alert arrives: all stages → `done`, show "Knowledge Graph ready" button
- Fallback: if no alert within 60s, show "Continue to dashboard" button anyway

### Step 12 — New `services/delivery/src/app/api/search/route.ts`
- Proxies `POST` to `{AGGREGATOR_URL}/search`, returns 202 with `search_id`

### Step 13 — Dashboard reads `?q=` param
- `services/delivery/src/app/dashboard/page.tsx` reads `useSearchParams()` `?q=` value
- Pre-fills `FilterToolbar` search field with the query on mount

---

## Phase 5 — Dashboard → Real Neo4j + Graph Filter
*Depends on Phase 4*

### Step 14 — `services/delivery/src/lib/neo4j.ts` (new)
- `getDriver()` singleton using `neo4j-driver` npm package
- Config from env: `NEO4J_URL` (bolt://neo4j:7687), `NEO4J_USER`, `NEO4J_PASSWORD`
- Module-level singleton (not created per request — avoids connection pool exhaustion)

### Step 15 — Replace `services/delivery/src/app/api/graph/route.ts` (mock → real)
- Cypher:
  ```
  MATCH (n:STIXEntity {tenant_id: $t})
  OPTIONAL MATCH (n)-[r]->(m:STIXEntity {tenant_id: $t})
  RETURN n, r, m LIMIT 500
  ```
- Map Neo4j `Node` → `GraphNode`: `id=n.id`, `label=n.name`, `stixType=n.stix_type`, `communityId=n.community_id`, `confidence=n.confidence`, `x/y=random*1000`
- Map `Relationship` → `GraphEdge`: `id=elementId`, `source=start.id`, `target=end.id`, `label=type`
- Accept `?tenant_id=dev-tenant` (default)
- Fallback to empty `{nodes:[], edges:[]}` on Neo4j error

---

## Phase 6 — Docker Compose + Config
*Parallel with Phase 2*

### Step 16 — `infrastructure/docker-compose.yml`
- Add 4 plugin services (`mcp-wikipedia`, `mcp-wikidata`, `mcp-newsrss`, `mcp-reuters`) under `services` + `all` profiles, ports 8091-8094
- Add `NEO4J_URL`, `NEO4J_USER`, `NEO4J_PASSWORD`, `AGGREGATOR_URL` to delivery service `environment`

### Step 17 — `.env.docker.example`
- Append: `MCP_PLUGIN_URLS=http://mcp-echo:8090,http://mcp-wikipedia:8091,http://mcp-wikidata:8092,http://mcp-newsrss:8093,http://mcp-reuters:8094`
- Append: `AGGREGATOR_URL`, `NEO4J_URL/USER/PASSWORD` entries for delivery

---

## Verification

| # | Test | Method |
|---|------|--------|
| 1 | Prompt registry unit tests | `uv run pytest tests/test_extractor.py -k "prompt"` |
| 2 | Wikipedia plugin | `cd mcp-plugins/wikipedia && go test ./...` |
| 3 | Wikidata plugin | `cd mcp-plugins/wikidata && go test ./...` |
| 4 | Aggregator `/search` handler | `go test -race ./internal/server/...` |
| 5 | Delivery graph API (mock neo4j-driver) | `pnpm test` |
| 6 | **Full E2E smoke test** | Start all services → Open `localhost:3000` → Type "Sundar Pichai" → Search → Watch progress stages → "Knowledge Graph ready" → Click → Graph shows Identity nodes, edges, community summary in FocusPanel |
| 7 | Entity merge validation | Search "Google CEO" → Neo4j Browser `MATCH (n:STIXEntity) RETURN n` → verify SAME_AS edge to Pichai node |
| 8 | News vs biographical prompt | LLM extraction logs show different `source_type` values per event; nodes have `created_by_ref` tracking source |

---

## Relevant Files

**New:**
- `services/processor/src/llm/prompts.py`
- `mcp-plugins/wikipedia/{main.go,go.mod,Dockerfile}`
- `mcp-plugins/wikidata/{main.go,go.mod,Dockerfile}`
- `mcp-plugins/newsrss/{main.go,go.mod,Dockerfile}`
- `mcp-plugins/reuters/{main.go,go.mod,Dockerfile}`
- `services/aggregator/internal/server/search_handler.go`
- `services/delivery/src/components/PipelineProgress.tsx`
- `services/delivery/src/app/api/search/route.ts`
- `services/delivery/src/lib/neo4j.ts`

**Modified:**
- `services/processor/src/llm/extractor.py` — use `PromptRegistry`, pass `source_type`
- `services/aggregator/internal/server/server.go` — register `/search`
- `services/aggregator/cmd/aggregator/main.go` — wire `SearchHandler`
- `services/delivery/src/app/page.tsx` — replace with search bar + inline progress UI
- `services/delivery/src/app/api/graph/route.ts` — replace mock with Neo4j
- `services/delivery/src/app/dashboard/page.tsx` — read `?q=` param
- `infrastructure/docker-compose.yml` — 4 new plugins, delivery env
- `.env.docker.example`

**Reference patterns:**
- `mcp-plugins/echo/main.go` — exact plugin pattern for all 4 new plugins
- `services/aggregator/internal/scheduler/scheduler.go` — tool-call loop to replicate in SearchHandler
- `services/aggregator/internal/server/server.go` — how to wire handlers
- `services/aggregator/cmd/aggregator/main.go` — dependency injection pattern

---

## Decisions
- **4 OSINT plugins**: Wikipedia (biographical text), Wikidata (structured facts), Google News RSS, Reuters RSS — all free, no auth
- **Prompt architecture**: `prompts.py` as single maintainable file; `source_type` metadata field routes to correct prompt at extraction time; future: load from YAML for non-developer editing
- **Pipeline progress UX**: Time-based simulation (not real Kafka events) — sufficient for M5, avoids pipeline instrumentation. WebSocket `alert` event acts as real done signal
- **Home = search only**: `page.tsx` becomes the entry point; dashboard only reachable after search (or via direct URL for returning users)
- `tenant_id=dev-tenant` for all local testing; no auth enforcement (M6 scope)

## Further Considerations
1. **`_calculate_confidence()` in extractor** — currently scores based on entity count only. For Wikidata facts (which are terse), this may score too low. Add a `source_type` multiplier: biographical/wikidata sources get a 0.1 confidence boost since they're authoritative structured data.
2. **Wikidata SPARQL query design** — the SPARQL endpoint requires a well-crafted query. For "Sundar Pichai", search by `rdfs:label` with `OPTIONAL` clauses for each fact type to avoid empty result sets when properties are missing. This is the most complex part of the Wikidata plugin.
3. **Google News RSS rate limiting** — Google News RSS doesn't require auth but may throttle repeated queries. Reuters RSS is a stable fallback. Consider a configurable RSS URL override via env var per plugin for easy swapping.
4. **Neo4j driver in Next.js** — Bolt connections from serverless Next.js route handlers can exhaust connection pools. The `getDriver()` singleton in `src/lib/neo4j.ts` must use a connection pool (default) and must not close the driver per request.
