# MCP Server Setup Guide

**Audience:** Plugin developers building new data sources for Omni-G
**Status:** Current as of M3.1

---

## Overview

Omni-G ingests threat intelligence from external data sources through the **Model Context Protocol (MCP)**. Each data source is packaged as a standalone MCP *plugin server*. The Aggregator service acts as the MCP *host*: it polls every registered plugin on a configurable schedule, validates the returned events, and publishes them to Kafka.

```
┌──────────────────────────────────────────────────────┐
│                    Aggregator                         │
│                                                       │
│  Scheduler ──► MCP Client ──► (your plugin)          │
│                    │                                  │
│              Pipeline                                 │
│           ┌───────┴────────┐                         │
│       Validator          Publisher                    │
│      (Processor)         (Kafka)                      │
└──────────────────────────────────────────────────────┘
```

---

## Protocol Reference

Plugins communicate using **JSON-RPC 2.0** over **HTTP**. The Aggregator makes two types of requests:

### 1. `tools/list` — discovery

The Aggregator calls `POST /` on the plugin with:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/list"
}
```

The plugin responds with its list of tools:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "tools": [
      {
        "name": "fetch_iocs",
        "description": "Fetches recent indicators of compromise",
        "inputSchema": {
          "type": "object",
          "properties": {
            "source":  { "type": "string" },
            "payload": { "type": "object" }
          },
          "required": ["source", "payload"]
        }
      }
    ]
  }
}
```

### 2. `tools/call` — invocation (SSE streaming)

After listing tools, the Aggregator calls each one via `POST /sse`:

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/call",
  "params": {
    "name": "fetch_iocs",
    "arguments": {}
  }
}
```

The plugin **must** respond with `Content-Type: text/event-stream` and stream results as Server-Sent Events:

```
data: {"type":"text","text":"{\"source\":\"my-plugin\",\"payload\":{...}}"}

data: {"type":"text","text":"{\"source\":\"my-plugin\",\"payload\":{...}}"}

data: [DONE]

```

Each `data:` line carries a JSON-encoded `ContentBlock`:

| Field  | Type   | Values              |
|--------|--------|---------------------|
| `type` | string | `"text"` or `"image"` |
| `text` | string | JSON-encoded event payload (when `type = "text"`) |

The stream ends with a literal `data: [DONE]` sentinel. The Aggregator closes the connection after receiving it.

### Event payload format

The `text` field of each `ContentBlock` must be a JSON object that the Processor `/validate` endpoint will accept. The required top-level fields are:

| Field     | Type   | Description                         |
|-----------|--------|-------------------------------------|
| `source`  | string | Stable identifier for the data source (e.g. `"shodan"`) |
| `payload` | object | Arbitrary, plugin-specific event data |

Example:

```json
{
  "source": "shodan",
  "payload": {
    "ip": "1.2.3.4",
    "port": 22,
    "banner": "SSH-2.0-OpenSSH_8.9p1"
  }
}
```

---

## Building a Plugin

### File structure

```
mcp-plugins/
└── my-plugin/
    ├── main.go      (or app.py / index.ts)
    ├── go.mod       (or pyproject.toml / package.json)
    └── Dockerfile
```

### Minimal Go plugin

The `mcp-plugins/echo/` directory contains a fully working reference implementation. Copy it as a starting point:

```bash
cp -r mcp-plugins/echo mcp-plugins/my-plugin
cd mcp-plugins/my-plugin
# Edit go.mod module name and main.go
```

Key sections to customise in `main.go`:

```go
// 1. Register your tools
var registeredTools = []tool{
    {
        Name:        "fetch_iocs",
        Description: "Fetches recent indicators of compromise",
        InputSchema: json.RawMessage(`{
            "type": "object",
            "properties": {
                "source":  {"type": "string"},
                "payload": {"type": "object"}
            },
            "required": ["source", "payload"]
        }`),
    },
}

// 2. Implement tool logic in handleSSE — for each tool call, stream
//    ContentBlocks via SSE.
func handleSSE(w http.ResponseWriter, r *http.Request) {
    // ... parse params, fetch data, then:
    for _, event := range fetchedEvents {
        text, _ := json.Marshal(event)
        block := contentBlock{Type: "text", Text: string(text)}
        data, _ := json.Marshal(block)
        fmt.Fprintf(w, "data: %s\n\n", data)
        flusher.Flush()
    }
    fmt.Fprintf(w, "data: [DONE]\n\n")
    flusher.Flush()
}
```

### Minimal Python plugin

```python
# mcp-plugins/my-plugin/app.py
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
import json, asyncio

app = FastAPI()

TOOLS = [{"name": "fetch_iocs", "description": "...", "inputSchema": {}}]

@app.post("/")
async def rpc(req: Request):
    body = await req.json()
    if body["method"] == "tools/list":
        return {"jsonrpc": "2.0", "id": body["id"], "result": {"tools": TOOLS}}
    return {"jsonrpc": "2.0", "id": body["id"],
            "error": {"code": -32601, "message": "method not found"}}

@app.post("/sse")
async def sse(req: Request):
    async def generate():
        events = await fetch_events()        # your data-source call
        for ev in events:
            block = json.dumps({"type": "text", "text": json.dumps(ev)})
            yield f"data: {block}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
```

---

## Dockerfile

Every plugin must ship a `Dockerfile`. Use multi-stage builds to keep images small:

```dockerfile
# Go example
FROM golang:1.22-alpine AS builder
WORKDIR /app
COPY go.mod .
COPY main.go .
RUN go build -o plugin .

FROM alpine:3.19
RUN adduser -D -u 1000 appuser
USER appuser
WORKDIR /app
COPY --from=builder /app/plugin .
EXPOSE 8090
ENV PORT=8090
HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
    CMD wget -qO- http://localhost:${PORT}/health || exit 1
ENTRYPOINT ["./plugin"]
```

The health check endpoint (`GET /health`) is **required** — Docker Compose waits for it before the Aggregator starts polling.

---

## Registering a Plugin

### Local development

Add the plugin to `docker-compose.test.yml` alongside the Aggregator:

```yaml
services:
  my-plugin:
    build:
      context: mcp-plugins/my-plugin
      dockerfile: Dockerfile
    environment:
      PORT: "8091"
    healthcheck:
      test: ["CMD-SHELL", "wget -qO- http://localhost:8091/health || exit 1"]
      interval: 5s
      timeout: 3s
      retries: 5
    profiles: [test]
    networks: [omni-g]

  aggregator:
    environment:
      MCP_PLUGIN_URLS: "http://my-plugin:8091"   # comma-separate multiple
      SCHEDULER_INTERVAL_MS: "10000"             # poll every 10s
```

### Production (Docker Compose)

In `infrastructure/docker-compose.yml`, add the plugin under the `services` profile and set `MCP_PLUGIN_URLS` on the Aggregator:

```yaml
# infrastructure/docker-compose.yml
services:
  my-plugin:
    image: ghcr.io/omni-g/mcp-my-plugin:latest
    profiles: [services]
    networks: [omni-g]
    environment:
      PORT: "8091"
    healthcheck: ...

  aggregator:
    environment:
      MCP_PLUGIN_URLS: "http://my-plugin:8091,http://other-plugin:8092"
```

### Discovering registered plugins

The Aggregator exposes its own `GET /mcp/tools` endpoint that lists all currently registered plugin URLs:

```bash
curl http://localhost:8080/mcp/tools | jq .
```

```json
{
  "jsonrpc": "2.0",
  "id": null,
  "result": {
    "tools": [
      { "name": "http://my-plugin:8091", "description": "MCP plugin data source" }
    ]
  }
}
```

---

## Aggregator Configuration Reference

| Variable               | Default            | Description                                    |
|------------------------|--------------------|------------------------------------------------|
| `MCP_PLUGIN_URLS`      | *(empty)*          | Comma-separated list of plugin base URLs        |
| `SCHEDULER_INTERVAL_MS`| `30000`            | Milliseconds between successive polls per plugin |
| `VALIDATION_SERVICE_URL`| `http://localhost:8001` | Processor sidecar for schema validation   |
| `KAFKA_BROKERS`        | `localhost:9092`   | Kafka bootstrap servers                         |
| `KAFKA_TOPIC`          | `raw-feed`         | Topic for validated events                      |
| `KAFKA_DLQ_TOPIC`      | `raw-feed.dlq`     | Dead-letter topic (wired in M3.4)               |

---

## Scheduler Behaviour

The Aggregator runs one goroutine per plugin. Each goroutine:

1. Calls `tools/list` on the plugin to get the current tool catalogue.
2. Calls each tool in sequence via `tools/call` (SSE), forwarding every `ContentBlock` through the validate → publish pipeline.
3. Waits `SCHEDULER_INTERVAL_MS` before the next cycle.

**Backoff on failure:** If `tools/list` fails, the goroutine retries up to 5 times using exponential backoff (500 ms × 2ⁿ, capped at 60 s). After 5 failures the poll attempt is counted as an error in Prometheus and the goroutine resumes the normal interval.

**Metrics** (scraped at `GET /metrics`):

| Metric                             | Labels                    | Description                        |
|------------------------------------|---------------------------|------------------------------------|
| `omni_g_scheduler_poll_total`      | `plugin_url`, `status`    | Poll cycles (ok / error)           |
| `omni_g_ingest_total`              | `source`, `status`        | Events processed (published / validation_failed / ...) |
| `omni_g_validation_failure_total`  | `source`, `reason`        | Events rejected by the sidecar     |
| `omni_g_kafka_publish_total`       | `topic`, `status`         | Kafka produce attempts (ok / error)|
| `omni_g_event_processing_duration_seconds` | —               | Validate + publish latency         |

---

## Testing a Plugin

### Unit test (httptest)

```go
func TestMyPlugin_ListTools(t *testing.T) {
    // Start your plugin handler inline:
    srv := httptest.NewServer(http.HandlerFunc(handleRPC))
    defer srv.Close()

    c := mcp.NewClient(srv.URL)
    tools, err := c.ListTools(context.Background())
    require.NoError(t, err)
    assert.Len(t, tools, 1)
    assert.Equal(t, "fetch_iocs", tools[0].Name)
}
```

### Integration test

```bash
# Start the echo plugin + Aggregator together:
docker compose -f docker-compose.test.yml --profile test up \
    mcp-echo aggregator --abort-on-container-exit

# Check metrics to confirm events were published:
curl -s http://localhost:8080/metrics | grep omni_g_ingest_total
```

### Manual smoke test

```bash
# 1. Start the plugin locally
cd mcp-plugins/echo && go run . &

# 2. Test tools/list
curl -s -X POST http://localhost:8090 \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | jq .

# 3. Test tools/call (SSE)
curl -s -X POST http://localhost:8090/sse \
  -H 'Content-Type: application/json' \
  -H 'Accept: text/event-stream' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"echo","arguments":{"source":"test","payload":{"key":"value"}}}}'
```

Expected output for step 3:

```
data: {"type":"text","text":"{\"source\":\"test\",\"payload\":{\"key\":\"value\"},\"echoed_at\":\"...\"}"}

data: [DONE]
```

---

## Error Handling

| Scenario | Plugin should return | Aggregator behaviour |
|---|---|---|
| Tool invocation fails | JSON-RPC error object (code + message) | Logs error, increments `omni_g_scheduler_poll_total{status="error"}`, continues |
| Invalid event payload | Emit the event anyway | Validation sidecar rejects it; increments `omni_g_validation_failure_total` |
| Plugin unavailable | — (connection refused) | Exponential backoff up to 60 s, then resumes normal interval |
| Malformed SSE line | — (bad JSON) | Silently dropped; `omni_g_ingest_total{status="parse_error"}` incremented |

---

## Checklist: Shipping a New Plugin

- [ ] `POST /` handles `tools/list` and returns at least one tool
- [ ] `POST /sse` responds with `Content-Type: text/event-stream` and streams `ContentBlock` objects
- [ ] Every event includes `source` (non-empty string) and `payload` (object)
- [ ] Stream ends with `data: [DONE]`
- [ ] `GET /health` returns `200 OK`
- [ ] `Dockerfile` builds a working image with a health check
- [ ] Plugin added to `docker-compose.test.yml` and verified with integration test
- [ ] `MCP_PLUGIN_URLS` updated in the relevant Docker Compose file
