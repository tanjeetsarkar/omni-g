# **Project Omni-G: A Next-Generation AI-Powered Knowledge Graph Platform for General Intelligence Gathering**

## **Executive Summary**

The modern world is defined not by a scarcity of information, but by a crisis of synthesis. Across every domain—business, research, journalism, security, finance, policy—the exponential proliferation of publicly available data has created a "cognitive bandwidth gap" where the velocity of information far outstrips the human capacity for analysis. Researchers and analysts today are besieged by a torrent of disparate signals—news articles, social media, corporate filings, research publications, and public databases—creating a chaotic noise floor where critical insights are frequently obscured. Traditional knowledge management tools suffer from monolithic architectures, proprietary data lock-in, and a "retrieval-centric" philosophy that places the burden of discovery entirely on the user.
This white paper introduces **Omni-G**, a distributed, event-driven Knowledge Graph platform designed to bridge this gap across any domain. Building upon the architectural principles of "Radio-G"—an AI-powered news aggregation system that successfully leveraged Apache Kafka, Google Cloud, and Generative AI to democratize access to global narratives —Omni-G reframes the challenge of intelligence gathering. It moves beyond the static paradigm of "search" to a dynamic, real-time paradigm of "synthesis." Just as Radio-G transforms static text into a "lean-back" audio experience, effectively broadcasting relevant news to users , Omni-G transforms unstructured OSINT data points into a living, queryable Knowledge Graph that proactively "broadcasts" actionable insights to analysts before they even formulate the query.
This document serves as a comprehensive blueprint for the Omni-G platform. It articulates a strategic philosophy rooted in "Cognitive Resonance," details a market-viable business model based on a developer-centric plugin economy powered by the Model Context Protocol (MCP), and provides an exhaustive technical specification of the platform’s three core pillars: the Aggregator, the Processor, and the Delivery engine. By synthesizing the event-driven agility of Radio-G with the cognitive depth of Graph Retrieval-Augmented Generation (GraphRAG) and the rigorous security of multi-tenant sandboxing, Omni-G represents a paradigm shift in how the IC interacts with the world's information.

## **1\. Application Philosophy: From Data Retrieval to Cognitive Resonance**

### **1.1 The Crisis of the "Retrieval-Centric" Model**

The prevailing philosophy of current Business Intelligence (BI) and OSINT tools is fundamentally "Retrieval-Centric." Platforms such as Maltego, while powerful in their visualization capabilities, operate on a reactive model: an analyst must actively query for specific entities—searching for a known IP address, a specific person of interest, or a targeted organization. This model relies on a critical, often flawed assumption: that the analyst already knows what they are looking for. In an era characterized by hybrid warfare, non-linear supply chain obfuscation, and grey-zone activities, the primary threat vectors are invariably the "unknown unknowns."
A retrieval-centric architecture is inherently limited by the analyst’s available attention and prior knowledge. It creates a bottleneck where the system is passive, waiting for human input to initiate processing. This latency—between the emergence of a threat signal in the wild and the analyst’s query—is where intelligence failures occur. Furthermore, the sheer volume of data creates a "linguistic digital divide," as identified in the Radio-G project, where vast populations of data remain inaccessible due to language barriers or sheer volume. In the IC, this manifests as a "technical capability divide," where advanced graph analytics are restricted to specialized data scientists using complex query languages like Cypher or SPARQL, leaving field agents and policymakers reliant on static reports.

### **1.2 The Omni-G Philosophy: Synthesis-Centric Intelligence**

Omni-G adopts a "Synthesis-Centric" philosophy. Drawing direct inspiration from Radio-G's concept of an "autonomous, intelligent news anchor," Omni-G functions as an autonomous knowledge curator that never sleeps. It does not passively await queries. Instead, it continuously ingests high-velocity streams of data, resolves entities against an existing Knowledge Graph, and identifies relationships, emerging narratives, or structural changes in real-time.
The core objective of Omni-G is **Cognitive Resonance**—a state in which the system's internal model of the world (the Knowledge Graph) aligns with external reality in near real-time, allowing it to proactively "push" alerts and surface new connections before the user formulates the query. This shift from "Pull" to "Push" fundamentally alters how users interact with information:

* **Ingestion is Translation:** Omni-G translates *unstructured data* (text, articles, documents) into *structured knowledge* (entities, relationships, events) that can be reasoned about at scale.
* **State is a Stream:** The "current state" of the world is merely a snapshot of an infinite event stream. By utilizing Apache Kafka as the central nervous system, Omni-G ensures that knowledge is never stale; the graph is updated as new data arrives.
* **Deduping as Intelligence:** One of the key learnings from Radio-G was that "the most important code is often the code that decides when *not* to call the AI." Omni-G applies this via rigorous cryptographic hashing and entity resolution. By preventing circular reporting—where a single report echoes across multiple sources and appears as corroboration—the system acts as a filter for signal, not just a bucket for noise.

### **1.3 The "Lean-Back" Experience**

The Radio-G project prioritized a "lean-back" experience, allowing users to consume information via audio while multitasking. Omni-G adapts this for any knowledge-intensive workflow. Users who cannot always engage with a complex dashboard can receive AI-generated audio briefings synthesized from the latest graph changes. The platform synthesizes "Daily Situation Reports" tailored to the user's graph subscriptions—delivered by Kokoro TTS. For example: *"Overnight, the graph added 12 new entities connected to the Organization cluster you are tracking. Three new relationships were discovered with high confidence."* This decouples knowledge consumption from the screen and democratizes access to the Knowledge Graph.

## **2\. Market Research: The Plugin Economy & Business Models**

To ensure long-term viability, scalability, and continuous innovation, Omni-G is designed not as a monolithic software product, but as a **Multi-Sided Platform (MSP)**. The history of enterprise software—from the decline of monolithic ERPs to the rise of ecosystems like Snowflake and Atlassian—demonstrates that the ultimate value lies in the ecosystem, specifically in the marketplace of third-party plugins and data connectors.

### **2.1 The Failure of Closed OSINT Ecosystems**

Traditional OSINT platforms have historically relied on a "walled garden" approach. Vendors integrate a fixed, curated set of data providers (e.g., WhoisXML, Shodan, LexisNexis) and charge a premium for access. While this provides a baseline of capability, it creates significant bottlenecks:

* **Integration Lag:** Integrating a new, niche data source (e.g., a specific regional forum, a new cryptocurrency ledger, or a leaked database) requires vendor intervention and lengthy development cycles.
* **Cost Scaling:** Pricing models often punish data volume, discouraging the comprehensive collection required for effective graph analysis.
* **Vendor Lock-in:** Users are trapped in the vendor’s ontology and visualization tools, making it difficult to export data or overlay proprietary internal intelligence.

### **2.2 The "Connector Marketplace" Opportunity**

The Omni-G business model pivots to a **Developer-Centric Plugin Ecosystem**, mirroring the successful strategies employed by Snowflake’s Data Marketplace and the emerging adoption of the Model Context Protocol (MCP). By opening the platform to third-party developers, Omni-G transforms from a tool into a utility.

#### **2.2.1 Profitable Business Model Architectures**

Comprehensive analysis of successful plugin ecosystems suggests three primary revenue levers for Omni-G, creating a diversified income stream that aligns the interests of the platform, the developer, and the agency.

| Revenue Model | Description | Precedent | Omni-G Implementation Strategy |
| :---- | :---- | :---- | :---- |
| **Compute/Usage Spread** | Revenue is generated based on the compute resources (CPU/GPU/RAM) consumed by the plugin's execution. | **Snowflake Native Apps** | Omni-G charges for the Cloud Run/Kubernetes compute time used to execute a plugin's extraction logic. The platform creates a margin between the raw infrastructure cost and the billed rate to the agency. This aligns revenue with system usage and intensity. |
| **Revenue Share (RevShare)** | Third-party developers charge a subscription or per-call fee for their specialized plugin; the platform takes a cut (typically 20-30%). | **RapidAPI, OpenAI GPT Store** | Developers create specialized OSINT collectors (e.g., "Russian Dark Web Forum Scraper" or "Maritime AIS Anomaly Detector"). Users subscribe to these connectors via the Omni-G Hub. Omni-G retains 25% of the subscription fee, handling billing, auth, and hosting. |
| **Data Enrichment Credits** | Users purchase platform "credits" used to "unlock" premium data attributes within the graph. | **Maltego Data Pass** | Basic nodes (e.g., an IP address) are free to visualize. Enriching that node with premium threat intelligence (e.g., CrowdStrike behavior data or historic Whois) costs credits. The data provider gets paid per enrichment, incentivizing granular, high-value data integration. |

#### **2.2.2 The Strategic Moat: Model Context Protocol (MCP)**

A critical differentiator for Omni-G is the adoption of the **Model Context Protocol (MCP)** as the standard for plugins. Unlike proprietary plugin architectures (such as the now-deprecated OpenAI Plugins or specific LangChain tools), MCP is an open standard that allows a single connector to serve multiple AI clients (Claude, IDEs, and Omni-G).

* **Reducing the "Cold Start" Problem:** By supporting MCP, Omni-G instantly taps into an existing ecosystem of pre-built connectors (Google Drive, Slack, GitHub, Postgres, SQLite). Developers do not need to build *for* Omni-G specifically; they build for MCP, and Omni-G consumes it.
* **Developer Incentive:** Developers build a connector once for the broader MCP ecosystem and can instantly monetize it on the Omni-G marketplace without rewriting code for a proprietary standard. This drastically lowers the barrier to entry for niche intelligence providers.

### **2.3 Strategic Positioning vs. Competitors**

* **Vs. Palantir:** Palantir operates on a high-cost, heavy-service consulting model, often requiring months of forward-deployed engineering to integrate. Omni-G offers a self-service, plugin-extensible model with a "bring your own data" philosophy via MCP, allowing teams to start small and scale.
* **Vs. Maltego:** Maltego relies on client-side transforms and a visual-first approach, where processing happens on the user's machine. Omni-G focuses on *server-side* continuous processing (Event-Driven) and *semantic* understanding (GraphRAG), ensuring that the knowledge graph is alive and reasoning even when the user is offline.
* **Vs. Snowflake:** Snowflake is a general-purpose data warehouse. While it stores data effectively, it lacks the native *semantic* understanding of entities and relationships that Omni-G provides. Omni-G is an application layer *on top* of data, not just a storage layer.

## **3\. Technical Architecture: The Omni-G Engine**

The architecture of Omni-G leverages the **Aggregator-Processor-Delivery** pattern established in Radio-G, upgraded for high-throughput knowledge graph workloads. It uses a microservices architecture deployable on Docker Compose locally or Kubernetes in production, orchestrated by **Apache Kafka** for high-throughput event streaming.

### **3.1 Component 1: The Aggregator (The "Senses")**

The Aggregator is the ingestion layer, responsible for monitoring the external world and pulling data into the system. In Radio-G, this was a simple RSS fetcher. In Omni-G, this is a sophisticated **Federated MCP Client** capable of handling thousands of concurrent data streams.

#### **3.1.1 MCP-Native Ingestion Architecture**

Instead of hard-coding API integrations for Twitter, Telegram, or Shodan, the Aggregator functions as an **MCP Host**. It connects to a dynamic registry of "MCP Servers"—the plugins.

* **Discovery Mechanism:** The Aggregator queries the tools/list endpoint of active MCP servers to discover capabilities (e.g., search\_twitter, query\_shodan, fetch\_corporate\_registry). This creates a dynamic "menu" of capabilities that the system can invoke.
* **Agentic Scheduling:** An AI "Scheduler Agent" determines *when* to call these tools based on standing intelligence requirements. For example, if the threat level for a specific geographic region increases, the Scheduler Agent automatically increases the polling frequency of relevant MCP servers (e.g., local news scrapers, Telegram monitors) to ensure higher fidelity data.

#### **3.1.2 The "Raw Event" Pipeline**

Data ingested from MCP servers is immediately serialized into JSON and pushed to the raw-intelligence-feed Kafka topic.

* **Edge Schema Enforcement:** We utilize **Pydantic** models to enforce strict schema validation at the edge. This ensures that "garbage in, garbage out" is mitigated early. If a plugin returns malformed data or data that violates the schema constraints, it is rejected before it can pollute the downstream processing pipeline.
* **Provenance Metadata:** Every event is tagged with extensive metadata: Source ID, Plugin Version, Timestamp, Latency, and a Confidence Score. The source of information is as important as the information itself—provenance metadata enables users to trace any claim in the graph back to the originating plugin and event.

### **3.2 Component 2: The Processor (The "Brain")**

The Processor is the heart of Omni-G. It consumes the raw-intelligence-feed, transforms unstructured data into structured knowledge, and persists it into the Knowledge Graph. This layer replaces the simple "Summarizer" in Radio-G with a complex **GraphRAG Engine**.

#### **3.2.1 Step 1: Deduplication & State Management (Redis)**

Following the Radio-G pattern, we use **Redis** for high-performance deduplication.

* **Content Hashing:** Incoming articles or reports are hashed using SHA-256. The hash is checked against Redis. If it exists, the system checks for updates. If the content is identical, processing is skipped to save AI inference costs—a lesson directly learned from Radio-G’s "Rate Limit Wall" findings.
* **Windowed Deduplication:** For high-velocity streams (e.g., social media botnets repeating the same message), Redis sets a sliding window to aggregate duplicates into a single "Cluster Event" rather than processing them individually. This reduces noise and computational overhead.

#### **3.2.2 Step 2: Entity & Relationship Extraction (LLM + Pydantic)**

Unique content is passed to the **Extraction Service**. This service utilizes Large Language Models via **pydantic-ai** to enforce structured output extraction.

* **Open-Ended Entity Model:** The LLM extracts entities of any type it determines from context—Person, Organization, Location, Event, Topic, Concept, and so on. Entity types are not constrained to a fixed ontology; the schema is generic (`type`, `name`, `description`, `properties`) allowing the graph to represent any domain.
* **Relationship Extraction:** Relationships between entities are also extracted with open-ended types (e.g., KNOWS, LOCATED_AT, PARTICIPATED_IN, PUBLISHED, FOUNDED) determined by the LLM from context.
* **Confidence Scoring:** Every extracted entity and relationship carries a confidence score (0.0–1.0) computed from the LLM's certainty and source quality. This score drives downstream merge decisions and alert thresholds.
* **Extensibility:** The `properties` dictionary on each entity allows domain-specific attributes without schema changes. Plugins can add structured data beyond what the base model captures.

#### **3.2.3 Step 3: Entity Resolution (The "Identity" Problem)**

A critical challenge in OSINT is knowing that "Robert Smith" in a corporate filing is the same as "Bob Smith" in a tweet. Omni-G employs a **Graph-Based Entity Resolution** engine.

* **Vector Blocking:** Entities are embedded into a vector space using models like OpenAI's text-embedding-3-small. A vector search (via Neo4j or Qdrant) identifies candidate matches based on semantic similarity, bypassing simple string matching limitations.
* **Graph Structural Matching:** The system analyzes the *neighborhood* of the entity. If "Robert Smith" and "Bob Smith" share the same phone number node and address node in the graph, the probability of a match increases exponentially.
* **Resolution Service:** High-confidence matches (e.g., \>95%) are automatically merged (creating a SAME\_AS edge or collapsing nodes). Low-confidence matches generate an "Ambiguity Alert" for human analysts to resolve, ensuring the machine does not introduce false positives into the intelligence record.

#### **3.2.4 Step 4: Knowledge Graph Construction (GraphRAG)**

The resolved entities and relationships are written to the **Knowledge Graph Database** (e.g., Neo4j or FalkorDB).

* **Community Detection:** Background workers run graph algorithms like **Leiden** or **Louvain** to detect "communities" of related nodes (e.g., a botnet cluster, a shell company ring, or a propaganda network).
* **GraphRAG Indexing:** Following Microsoft's GraphRAG methodology, the system generates natural language summaries for each community. This allows the LLM to answer global, high-level questions like "What are the main narratives regarding election interference in Eastern Europe?" by querying the pre-computed community summaries rather than retrieving and reading thousands of individual documents. This "Global Search" capability is what separates Omni-G from standard RAG systems.

### **3.3 Component 3: Delivery (The "Interface")**

The Delivery layer consumes the processed Knowledge Graph and presents it to the user through multiple modalities.

#### **3.3.1 The "Live Graph" Dashboard**

The Omni-G dashboard is a **search-first, interactive graph environment** built with **React Flow** (@xyflow/react).

* **Search-Driven Entry:** The user types a query. The system performs a semantic search against the vector database (Qdrant) to find the closest matching entities, then fetches their connected neighbors from Neo4j. The result is rendered as an interactive graph—no pre-loaded full graph.
* **Inline Node Information:** Every node displays its entity type, name, confidence score, and key properties directly inside the node. There are no sidebars or detail panels. Clicking a node expands its inline view to show additional properties seamlessly.
* **Real-Time Graph Growth:** When the Processor adds new entities connected to the current view, those nodes animate into the existing layout via force re-simulation. Disconnected new entities (not connected to current nodes) appear as a floating cluster at the edge of the canvas. The graph grows organically without a full reload.
* **Layout:** Initial layout uses a dagre (hierarchical) or force-directed algorithm. Incremental updates re-simulate only the affected neighborhood to avoid disorienting the user.

#### **3.3.2 The "Radio" Briefing (Audio Synthesis)**

Retaining the soul of Radio-G, Omni-G generates automated audio briefings.

* **Mechanism:** The GraphRAG engine generates a "Daily Situation Report" script based on the user's graph subscriptions and community summaries.
* **Synthesis:** Kokoro TTS (local, privacy-preserving) converts this script into an audio briefing, stored in MinIO and delivered via a signed URL. This allows users to consume a curated summary of graph changes while away from their screen.

#### **3.3.3 Agentic Action**

Beyond passive consumption, Omni-G supports **Action Plugins**.

* **Agent Protocol:** Using MCP, the system can act on intelligence. If a high-risk indicator is found, an agent can automatically trigger a firewall update (via a Palo Alto Networks plugin), initiate a deeper scan (via a Nmap plugin), or archive a webpage (via a Wayback Machine plugin). This moves the platform from "Intelligence" to "Response."

## **4\. Deep Dive: Component Interactions & Data Flow**

To illustrate the architecture in action, we trace the lifecycle of a single knowledge event: **A new news article published about a technology company announcing a major acquisition.**

### **4.1 Ingestion Phase (The Aggregator)**

1. **Trigger:** The **News RSS Plugin** (running as an isolated MCP Server) detects a new article matching monitored topics.
2. **Standardization:** The plugin formats the article into a standard JSON payload: `{source: "reuters", content: "...", timestamp: "..."}`.
3. **Transmission:** The Aggregator (MCP Client) receives this payload and validates it against the `RawEventEnvelope` Pydantic schema to ensure data integrity.
4. **Buffering:** The valid payload is produced to the `raw-feed` Kafka topic, ensuring the ingestion layer is decoupled from processing latency.

### **4.2 Processing Phase (The Processor)**

1. **Deduplication:** The **Ingestion Worker** reads the Kafka message. It computes a SHA-256 hash of the content. It queries Redis: `GET dedup:hash:xyz`. If the hash exists, the event is skipped. Otherwise, the key is set with a 24-hour TTL.
2. **Extraction:** The worker sends the content to the **LLM Extraction Service**. The LLM extracts:
   * Entity: Acme Corp (Type: Organization)
   * Entity: Sarah Chen (Type: Person, role: CEO)
   * Entity: GlobalTech Inc (Type: Organization)
   * Relationship: Acme Corp *acquires* GlobalTech Inc
   * Relationship: Sarah Chen *leads* Acme Corp
3. **Resolution:** The worker queries the Knowledge Graph (Neo4j) for "Acme Corp."
   * *Scenario A:* Node exists. The new relationship is added.
   * *Scenario B:* Node implies a match with "Acme Corporation" (semantic similarity > 90%). A `SAME_AS` edge is created.
4. **Persistence:** The graph is updated atomically. A downstream alert is published to `analyst-alerts` if confidence exceeds threshold.

### **4.3 Reasoning Phase (GraphRAG)**

1. **Community Update:** After graph persistence, the **GraphRAG Service** runs incremental community detection on the 2-hop neighborhood of newly added entities.
2. **Re-Summarization:** The service updates the natural-language summary of affected communities to include new entities and relationships.
3. **Insight Generation:** The updated summary is used to generate an alert: "New acquisition activity detected in the Technology sector community."

### **4.4 Delivery Phase (The Interface)**

1. **Notification:** The alert is published to the `analyst-alerts` Kafka topic.
2. **Frontend Update:** The **WebSocket Gateway** (subscribing to Kafka) pushes the alert to connected browser clients in real-time.
3. **Visual Growth:** On the React Flow dashboard, if the user has a relevant query active, new nodes (Acme Corp, GlobalTech Inc, Sarah Chen) animate into the existing graph layout. If the user has no active query, the new entities appear in a floating incoming cluster.
4. **Audio Brief:** If the user is offline, the alert is queued for their next GraphRAG-generated audio briefing.

## **5\. Security & Governance: Multi-Tenant Architecture**

Omni-G implements a **Zero-Trust, Multi-Tenant** architecture designed to keep knowledge graphs fully isolated across tenants while remaining extensible for future federated use cases.

### **5.1 Multi-Tenancy Patterns**

We employ a **Hybrid Multi-Tenancy** model to balance security and cost.

* **Data Isolation:** Each tenant has a logically isolated subgraph. In Neo4j, this is implemented via **Label-Based Access Control (LBAC)** or per-tenant labels. Every Kafka event, Redis dedup key, and Neo4j query carries a `tenant_id` ensuring complete data separation.
* **Federated Search:** Authorized super-users can execute **Federated Queries** that span multiple tenant graphs to surface cross-tenant connections, respecting data ownership boundaries.

### **5.2 Secure Plugin Execution (Sandboxing)**

Third-party plugins introduce security risk (RCE, data exfiltration). Omni-G mitigates this using **gVisor** and **Firecracker**.

* **Isolation:** Every MCP Server (plugin) runs in a dedicated **Firecracker MicroVM**. This provides hardware-level isolation, ensuring that a compromised plugin cannot access the host kernel or other plugins.
* **Network Policy:** Plugins are restricted by strict **Network Policies**. A plugin designed to scrape "Site A" is firewall-restricted to *only* access "Site A". It cannot "phone home" to a Command & Control (C2) server.
* **Output Validation:** All data leaving the sandbox must pass through a strict **Schema Validator**. Malformed or oversized payloads are dropped, preventing buffer overflow attacks on the Aggregator.

### **5.3 Data Provenance & Schema Governance**

Omni-G enforces schema discipline and data provenance without requiring a fixed ontology.

* **Open-Ended Schema:** Entity types are determined by the LLM at extraction time. The base schema (id, type, name, description, properties, confidence, source_id, tenant_id) is enforced by Pydantic at the processing edge. Custom attributes are captured in the `properties` dictionary.
* **Provenance:** Every entity and relationship carries `source_id` (the originating MCP plugin) and `confidence` (extraction certainty). This allows users to trace any fact in the graph back to its source event and plugin version.
* **Audit Trail:** All graph mutations are timestamped with `created` and `modified` fields. The `source_id` + `plugin_version` on every node provides a complete lineage chain.

## **6\. The "Agentic" Horizon**

The ultimate vision of Omni-G is to transition from a tool *used by* analysts to a teammate *collaborating with* analysts. By integrating **Agentic AI** workflows , Omni-G will evolve into a system that can:

1. **Hypothesize:** Detect a gap in the graph (e.g., "Who else is connected to this organization?") and automatically task collection plugins to fill it without human intervention.
2. **Simulate:** Run counter-factual scenarios on the Knowledge Graph ("What happens to this network if Node X is removed?").
3. **Self-Correct:** Automatically detect and flag low-confidence or contradictory data injected by unreliable sources, using graph-based anomaly detection.

Omni-G represents the convergence of the **Event Stream** (Radio-G's legacy), the **Knowledge Graph** (the reasoning engine), and the **Agentic Interface** (MCP). It is a platform for any organization that needs to understand complex, fast-moving domains at a scale no human team can match alone.

# **Detailed Architecture Specifications & Implementation Guide**

## **A. Aggregator Component (The "Senses")**

### **A.1 Functional Requirements**

* **Protocol Support:** Must natively support **MCP (Model Context Protocol)** over SSE (Server-Sent Events) for remote plugins and Stdio for local/sidecar plugins.
* **Throughput:** Capable of ingesting 10,000+ events per second (EPS) to handle global news feeds and social firehoses.
* **Resilience:** Implementation of the "Fan-Out Consumer" pattern to allow independent scaling of ingestion workers without bottlenecking the API.

### **A.2 Technical Stack**

* **Language:** Go (Golang) or Rust is recommended for high-concurrency performance and memory safety.
* **Framework:** genai-mcp libraries for protocol handling.
* **Queue:** Apache Kafka / Confluent Cloud for event buffering.
* **Validation:** Pydantic (via Python sidecars) or JSON Schema enforcement at the API Gateway level.

### **A.3 Workflow Description**

1. **Discovery:** The Aggregator queries the Service Registry (Consul/Etcd) to find available MCP Plugin Containers.
2. **Connection:** Establishes a persistent SSE connection to the Plugin.
3. **Polling/Listening:**
   * *Polling:* For REST APIs (e.g., RSS, NewsAPI), the plugin polls on a schedule defined by the Scheduler Agent.
   * *Streaming:* For streaming sources (e.g., Twitter Firehose, Bluesky), the plugin pushes events down the SSE pipe as they occur.
4. **Normalization:** The Aggregator wraps the plugin data in a standard **Omni-G Envelope**:
   `{`
     `"event_id": "uuid-v4",`
     `"source_plugin": "twitter-monitor-v1",`
     `"timestamp": "2025-01-01T12:00:00Z",`
     `"data_schema": "social_media_post",`
     `"payload": {... },`
     `"classification": "UNCLASSIFIED",`
     `"confidence_score": 0.85`
   `}`

5. **Dispatch:** The envelope is produced to the Kafka Topic raw-feed.

## **B. Processor Component (The "Brain")**

### **B.1 Functional Requirements**

* **Entity Extraction:** Automatically identify entities of any type the LLM determines from context—Persons, Organizations, Locations, Events, Topics, Concepts, and domain-specific types as needed.
* **Resolution:** Merge duplicates across data sources (e.g., "NYT" vs "New York Times").
* **Graph Construction:** Create nodes and edges in the graph database.

### **B.2 Technical Stack**

* **Compute:** Google Cloud Run (Serverless) or Knative on Kubernetes for auto-scaling based on queue depth.
* **State:** Redis Enterprise (for Deduplication & Entity Cache).
* **LLM:** Google Gemini 2.5 (for multimodal extraction) or Llama 3 (for on-prem/air-gapped deployments).
* **Graph DB:** Neo4j (Enterprise) or FalkorDB (Low latency, high throughput).
* **Orchestration:** LangChain or LangGraph (for multi-step reasoning workflows).

### **B.3 The Entity Resolution Pipeline (Algorithm)**

1. **Input:** Stream of ExtractedEntity objects from the LLM.
2. **Blocking:** Generate a "Blocking Key" (e.g., Soundex of Name \+ City) to group potential matches. Query Redis for candidate matches within that block.
3. **Pairwise Comparison:**
   * Calculate **Jaccard Similarity** on text fields (names, descriptions).
   * Calculate **Geo-Distance** on location fields.
   * Calculate **Graph Proximity** (Do they share neighbors? e.g., Same phone number).
4. **Decision Logic:**
   * Score \> 0.95 \-\> **Auto-Merge** (Collapse nodes).
   * Score \> 0.70 \-\> **Link** (Create POSSIBLE\_MATCH edge for analyst review).
   * Score \< 0.70 \-\> **Create New Node**.

## **C. Delivery Component (The "Voice/View")**

### **C.1 Functional Requirements**

* **Visualization:** Interactive, physics-based graph exploration.
* **Audio:** Text-to-Speech intelligence briefings.
* **Alerting:** Real-time push notifications via WebSockets.

### **C.2 Technical Stack**

* **Frontend:** React / Next.js.
* **Graph Library:** Sigma.js or Reagraph (WebGL) for rendering 100k+ nodes.
* **Audio Engine:** ElevenLabs API for high-fidelity speech synthesis.
* **Real-time:** WebSockets (Socket.io) connected to Kafka consumers for live updates.

### **C.3 The "Briefing" Logic**

1. **User Profile:** Defines "Topics of Interest" (e.g., "Cybersecurity in APAC", "Drug Trafficking in LatAm").
2. **Query:** Every morning (or on trigger), a job triggers a **GraphRAG Global Search**.
   * *Query:* "Summarize major changes in the graph related to 'Cybersecurity' and 'APAC' in the last 24 hours, highlighting new communities and high-risk nodes."
3. **Script Generation:** The LLM generates a radio-style script: "Good morning. In the last 24 hours, Omni-G detected a spike in chatter regarding the APT-29 group. A new cluster of domains has been linked to their infrastructure..."
4. **Synthesis:** The script is sent to ElevenLabs. The resulting audio file is stored in GCS/S3.
5. **Delivery:** A push notification is sent to the analyst's mobile app: "Your Morning Brief is ready."

## **Conclusion: The Omni-G Vision**

Omni-G is more than a software platform; it is a **doctrine**. It asserts that in a world of infinite data, the only sustainable competitive advantage is the **speed of synthesis**. By adopting the event-driven agility of Radio-G, upgrading it with the semantic rigor of Knowledge Graphs, and opening it to the world through the extensibility of MCP, Omni-G provides the Intelligence Community with the tool it desperately needs: A machine that doesn't just search for answers, but **listens for the truth**.

#### **Works cited**

1\. Open Source Intelligence Strategy \- United States Department of State, https://2021-2025.state.gov/open-source-intelligence-strategy/ 2\. Battling Malign Influence in the Open | AFCEA International, https://www.afcea.org/signal-media/intelligence/battling-malign-influence-open 3\. Maltego | OSINT & Cyber Investigations Platform for High-Stakes Cases, https://www.maltego.com/ 4\. Maltego vs. Palturai Comparison \- SourceForge, https://sourceforge.net/software/compare/Maltego-vs-Palturai/ 5\. 15 Best Graph Visualization Tools for Your Neo4j Graph Database, https://neo4j.com/blog/graph-visualization/neo4j-graph-visualization-tools/ 6\. Gotham | Palantir, https://www.palantir.com/platforms/gotham/ 7\. 5 Best OSINT Tools in 2025 \- Blackdot Solutions Videris, https://blackdotsolutions.com/blog/best-osint-tools 8\. What Is a Data Marketplace? | Informatica, https://www.informatica.com/resources/articles/what-is-data-marketplace.html 9\. Marketplace Monetization: Turn Your Data and Apps into a Revenue Stream \- Snowflake, https://www.snowflake.com/en/blog/marketplace-monetization-turn-data-apps-revenue-stream/ 10\. Which API Monetization Platform is Best? RapidAPI vs Moesif vs Zuplo, https://zuplo.com/learning-center/api-monetization-platforms 11\. How to Build Effective Revenue Models for AI Agent Marketplaces \- Monetizely, https://www.getmonetizely.com/articles/how-to-build-effective-revenue-models-for-ai-agent-marketplaces 12\. Introducing the Model Context Protocol \- Anthropic, https://www.anthropic.com/news/model-context-protocol 13\. Model Context Protocol, https://modelcontextprotocol.io/ 14\. Knowledge Graphs as MCP Tools: The New Bridge for LLM Grounding | by Vishal Mysore | Nov, 2025, https://medium.com/@visrow/knowledge-graphs-as-mcp-tools-the-new-bridge-for-llm-grounding-ce2e88932249 15\. Model Context Protocol (MCP) vs OpenAI's “Work with Apps” | by Hariharan Eswaran, https://medium.com/@hariharan.eswaran/model-context-protocol-mcp-vs-openais-work-with-apps-7e84f37b7a92 16\. Palantir Competitors: Understanding Alternatives to Gotham and Foundry \- DataWalk, https://datawalk.com/palantir-competitors-understanding-alternatives-to-gotham-and-foundry/ 17\. How does Palantir make money: Business Model & Competitor Analysis \- The Strategy Story, https://thestrategystory.com/2022/10/21/how-does-palantir-make-money-business-model-competitor-analysis/ 18\. Snowflake and Palantir Announce Strategic Partnership for Enterprise-Ready AI & Analytics, https://www.snowflake.com/en/news/press-releases/snowflake-palantir-announce-strategic-partnership-for-enterprise-ready-ai-analytics/ 19\. MCP vs gRPC Choosing AI Protocol. Compare MCP and gRPC for AI agents… | by Tahir, https://medium.com/@tahirbalarabe2/mcp-vs-grpc-choosing-ai-protocol-e4e160f6a6b2 20\. Shared Pydantic schemas as the basis for Kafka/Avro messages in SQuaRE Roundtable, https://sqr-076.lsst.io/ 21\. Deploy Pydantic K8s Kafka consumers | by Sirsh Amarteifio \- Medium, https://medium.com/@mrsirsh/deploy-pydantic-k8s-kafka-consumers-d1c4ec877481 22\. Knowledge Graph Extraction in Pydantic \- DEV Community, https://dev.to/jhagerer/knowledge-graph-extraction-in-pydantic-32on 23\. View open threat intelligence \- STIX/TAXII data \- Online Help Center, https://docs.trendmicro.com/en-us/documentation/article/security-management-system-64-user-help-view-stix-taxii-data 24\. STIX 2.1 Indicator Patterning and Detection Development | Filigran Blog, https://filigran.io/stix-2-1-indicator-patterning-and-detection-development/ 25\. Dynamic pydantic models \- IT racer \- Medium, https://itracer.medium.com/dynamic-pydantic-models-ac91e8acedcd 26\. What Is Entity Resolution? \- Neo4j, https://neo4j.com/blog/graph-database/what-is-entity-resolution/ 27\. No-code entity resolution & graph: The key to investigative analytics \- Linkurious, https://linkurious.com/blog/no-code-entity-resolution-graph-investigative-analytics/ 28\. rileylemm/graphrag\_mcp: This is a MCP server I built to interact with my hybrid graph rag db. \- GitHub, https://github.com/rileylemm/graphrag\_mcp 29\. Graph Database Multi-Tenant Cloud Security Architecture \- FalkorDB, https://www.falkordb.com/blog/graph-database-multi-tenant-cloud-security/ 30\. How to Build a Knowledge Graph: A Step-by-Step Guide \- FalkorDB, https://www.falkordb.com/blog/how-to-build-a-knowledge-graph/ 31\. Welcome \- GraphRAG, https://microsoft.github.io/graphrag/ 32\. Comparative Analysis of Graph Visualization Libraries | by Umid Muzrapov \- Medium, https://medium.com/@master-of-java/comperative-analysis-of-c0a7358ef50c 33\. reaviz/reagraph: WebGL Graph Visualizations for React. Maintained by @goodcodeus. \- GitHub, https://github.com/reaviz/reagraph 34\. A General Introduction To Graph Visualization Techniques \- DROPS, https://drops.dagstuhl.de/storage/01oasics/oasics-vol027-vluds2012-irtg1131/OASIcs.VLUDS.2011.151/OASIcs.VLUDS.2011.151.pdf 35\. 2 A Review of Overview+Detail, Zooming, and Focus+Context Interfaces \- College of Computing, https://faculty.cc.gatech.edu/\~stasko/7450/Papers/cockburn-surveys08.pdf 36\. Design Patterns for Building Multi-Tenant Applications on Snowflake, https://developers.snowflake.com/wp-content/uploads/2021/05/Design-Patterns-for-Building-Multi-Tenant-Applications-on-Snowflake.pdf 37\. Multi-Tenancy in Graph Databases and Why Should You Care? \- Memgraph, https://memgraph.com/blog/why-multi-tenancy-matters-in-graph-databases 38\. gVisor: The Container Security Platform, https://gvisor.dev/ 39\. Notes on sandboxing untrusted code \- why Python can't be sandboxed, comparing Firecracker/gVisor/WASM approaches \- GitHub Gist, https://gist.github.com/mavdol/2c68acb408686f1e038bf89e5705b28c 40\. Running Untrusted Python Code \- Andrew Healey, https://healeycodes.com/running-untrusted-python-code 41\. The agentic commerce opportunity: How AI agents are ushering in a new era for consumers and merchants \- McKinsey, https://www.mckinsey.com/capabilities/quantumblack/our-insights/the-agentic-commerce-opportunity-how-ai-agents-are-ushering-in-a-new-era-for-consumers-and-merchants 42\. Agentic AI: Model Context Protocol, A2A, and automation's future \- Dynatrace, https://www.dynatrace.com/news/blog/agentic-ai-how-mcp-and-ai-agents-drive-the-latest-automation-revolution/
