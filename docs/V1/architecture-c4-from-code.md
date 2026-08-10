# Omni-G UML Architecture (Code-Derived)

This document replaces the C4 views with UML-style Mermaid diagrams derived from implementation code in services/aggregator, services/processor, and services/delivery.

## 1) UML Class Diagram (System-Level Architecture)

```mermaid
classDiagram
direction TB

class Analyst {
  +submitSearch(query)
  +observeRealtimeUpdates()
}

class DeliveryUI {
  <<service>>
  +runSearch(query)
  +refreshGraph(query)
}

class DeliveryGateway {
  <<service>>
  +consumeAlerts()
  +broadcastSocketEvents()
}

class Aggregator {
  <<service>>
  +search(query, sources)
  +enrich(entity, plugins)
  +publishRawEvent()
}

class Processor {
  <<service>>
  +validate(payload)
  +processRawEvent(event)
  +searchGraph(query)
}

class Kafka {
  <<broker>>
  +raw_feed
  +raw_feed_dlq
  +analyst_alerts
  +processor_events
}

class Neo4j {
  <<database>>
}

class Redis {
  <<cache>>
}

class Qdrant {
  <<vector_db>>
}

class Ollama {
  <<llm>>
}

class MinIO {
  <<object_storage>>
}

class MCPPlugins {
  <<external_plugins>>
}

Analyst --> DeliveryUI : uses
DeliveryUI --> Aggregator : POST /search,/enrich
DeliveryUI --> Processor : POST /query,/entities,/briefings
DeliveryUI --> DeliveryGateway : socket join/subscribe

Aggregator --> MCPPlugins : tools/list, tools/call
Aggregator --> Processor : POST /validate
Aggregator --> Kafka : publish raw-feed

Processor --> Kafka : consume raw-feed\npublish alerts/events\nDLQ failures
Processor --> Redis : dedup check_and_set
Processor --> Qdrant : candidate match\nsemantic search
Processor --> Neo4j : persist/query graph
Processor --> Ollama : extraction/embeddings
Processor --> MinIO : briefing storage

DeliveryGateway --> Kafka : consume alerts/events
DeliveryGateway --> DeliveryUI : alert,pipeline_stage
```

## 2) UML Class Diagram (Delivery Service Internals)

```mermaid
classDiagram
direction TB

class DashboardPage {
  +runSearch(query)
  +refreshGraph(query)
  +handlePipelineComplete()
}

class APISearchRoute {
  +POST /api/search
}

class APIQueryRoute {
  +POST /api/query
}

class APIEntitiesRoute {
  +POST /api/entities
}

class UseRealtimeNodes {
  +handleAlert(payload)
  +fetchEntities(entityIds)
}

class SocketClient {
  +joinTenant(tenantId)
  +subscribe(params)
}

class GatewayServer {
  +handleKafkaMessageValue()
  +handleStageEventValue()
  +broadcastAlert()
}

class AggregatorAPI {
  <<external_api>>
}

class ProcessorAPI {
  <<external_api>>
}

class Kafka {
  <<broker>>
}

DashboardPage --> APISearchRoute : trigger ingestion
DashboardPage --> APIQueryRoute : query graph
DashboardPage --> SocketClient : websocket subscription

APISearchRoute --> AggregatorAPI : proxy /search
APIQueryRoute --> ProcessorAPI : proxy /search
APIEntitiesRoute --> ProcessorAPI : proxy /entities

SocketClient --> GatewayServer : join/subscribe
GatewayServer --> UseRealtimeNodes : alert,pipeline_stage
UseRealtimeNodes --> APIEntitiesRoute : hydrate entity IDs
GatewayServer --> Kafka : consume alerts/events
```

## 3) UML Class Diagram (Aggregator Service Internals)

```mermaid
classDiagram
direction TB

class HTTPServer {
  +registerRoutes()
  +Start(ctx)
}

class SearchHandler {
  +ServeHTTP()
  +callPlugin()
}

class EnrichHandler {
  +HandleEnrich()
}

class Scheduler {
  +RegisterPlugin()
  +Start(ctx, onBlock)
  +pollOnce()
}

class MCPClient {
  +ListTools()
  +CallTool()
}

class MCPHandler {
  +DiscoverTools()
  +UpdatePluginTools()
  +HandleToolsList()
}

class Pipeline {
  +Process()
  +ProcessBlock()
}

class ValidationClient {
  +Validate()
}

class KafkaProducer {
  +Publish(event)
}

class ProcessorValidateAPI {
  <<external_api>>
}

class PluginServers {
  <<external_plugins>>
}

class KafkaRawFeed {
  <<topic>>
}

HTTPServer --> SearchHandler : route /search
HTTPServer --> EnrichHandler : route /enrich
HTTPServer --> MCPHandler : route /mcp/tools
HTTPServer --> Scheduler : start background polling

SearchHandler --> MCPClient : tools/call(query)
EnrichHandler --> MCPClient : tools/call(focused query)
Scheduler --> MCPClient : tools/list/tools/call
Scheduler --> MCPHandler : update discovered tools
MCPClient --> PluginServers : JSON-RPC + SSE

SearchHandler --> Pipeline : ProcessBlock
EnrichHandler --> Pipeline : ProcessBlock
Scheduler --> Pipeline : onBlock -> ProcessBlock

Pipeline --> ValidationClient : validate payload
ValidationClient --> ProcessorValidateAPI : POST /validate
Pipeline --> KafkaProducer : publish RawEvent
KafkaProducer --> KafkaRawFeed : write raw-feed
```

## 4) UML Class Diagram (Processor Service Internals)

```mermaid
classDiagram
direction TB

class FastAPIApp {
  +startup_consumer()
  +POST /validate
  +POST /search
  +POST /entities
  +GET /briefings
  +POST /briefings/generate
}

class RawEventConsumer {
  +start()
  +process_messages(handler)
  +_send_to_dlq()
}

class ProcessingPipeline {
  +process(event)
}

class ContentDeduplicator {
  +check_and_set(tenantId, event)
}

class ZeroMemExtractor {
  +extract(eventId, text, metadata)
}

class EntityResolver {
  +resolve(tenantId, entity)
  +find_candidates()
  +find_structural_matches()
}

class GraphPersistenceService {
  +persist_extraction(result, tenantId)
  +search_entities(tenantId)
  +fetch_neighbor_entities(ids)
}

class GraphRAGIndexer {
  +index_incremental(tenantId, entityIds)
}

class AlertPublisher {
  +publish(alert)
}

class StageEventPublisher {
  +publish(eventId, tenantId, stage, status)
}

class BriefingModules {
  +generateOnDemand(tenantId)
  +listBriefings()
}

class Kafka {
  <<broker>>
}

class Redis {
  <<cache>>
}

class Qdrant {
  <<vector_db>>
}

class Neo4j {
  <<database>>
}

class Ollama {
  <<llm>>
}

class MinIO {
  <<object_storage>>
}

FastAPIApp --> RawEventConsumer : launch worker tasks
RawEventConsumer --> ProcessingPipeline : process(event)
RawEventConsumer --> Kafka : consume raw-feed\nsend DLQ

ProcessingPipeline --> ContentDeduplicator : stage dedup
ProcessingPipeline --> ZeroMemExtractor : stage extraction
ProcessingPipeline --> EntityResolver : stage resolution
ProcessingPipeline --> GraphPersistenceService : stage persistence
ProcessingPipeline --> GraphRAGIndexer : stage graphrag
ProcessingPipeline --> AlertPublisher : stage alert publish
ProcessingPipeline --> StageEventPublisher : stage telemetry

ContentDeduplicator --> Redis : dedup keys
ZeroMemExtractor --> Ollama : embeddings
EntityResolver --> Qdrant : vector candidates
EntityResolver --> Neo4j : structural matching
GraphPersistenceService --> Neo4j : write/read graph
GraphRAGIndexer --> Neo4j : community traversal
AlertPublisher --> Kafka : analyst-alerts
StageEventPublisher --> Kafka : processor-events

FastAPIApp --> BriefingModules : briefing endpoints
BriefingModules --> Neo4j : graph context
BriefingModules --> Ollama : summary/script generation
BriefingModules --> MinIO : audio storage and signed URL
```

## 5) UML Sequence Diagram (Search to Real-Time Graph Update)

```mermaid
sequenceDiagram
autonumber

actor Analyst
participant UI as Delivery UI
participant Agg as Aggregator
participant MCP as MCP Plugins
participant Val as Processor /validate
participant K as Kafka
participant Proc as Processor Pipeline
participant G as Delivery Gateway
participant Neo as Neo4j
participant Q as Qdrant

Analyst->>UI: Submit search query
UI->>Agg: POST /search
Agg->>MCP: tools/call(query)
MCP-->>Agg: ContentBlock stream
Agg->>Val: POST /validate
Val-->>Agg: {valid:true}
Agg->>K: Publish RawEvent (raw-feed)

K->>Proc: Consume raw-feed
Proc->>Proc: schema -> dedup -> extraction -> grounding
Proc->>Q: candidate matching
Proc->>Neo: persist entities/relationships
Proc->>K: Publish analyst-alerts
Proc->>K: Publish processor-events

K->>G: Consume alerts/events
G-->>UI: Socket alert + pipeline_stage

UI->>Proc: POST /query and /entities
Proc->>Q: semantic query search
Proc->>Neo: fetch neighbors + relationships
Proc-->>UI: entities + relationships
UI-->>Analyst: Updated graph with realtime nodes
