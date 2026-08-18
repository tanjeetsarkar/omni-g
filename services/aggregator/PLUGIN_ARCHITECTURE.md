# Omni-G Aggregator Plugin Architecture

## Overview

The Omni-G Aggregator uses a **pluggable MCP server architecture** inspired by OpenClaw's ClawHub. Each capability (web search, news search, etc.) runs as an independent MCP server plugin. The Aggregator discovers plugins at startup via `plugins.yaml`, connects to their MCP endpoints, and registers their tools with the 9-stage Harness for governed execution.

## Architecture

```
┌─────────────────┐     MCP (HTTP+SSE)      ┌──────────────────┐
│   Aggregator    │ ◄─────────────────────► │   Plugin (MCP)   │
│                 │   tools/list, tools/call │                  │
│  ┌───────────┐  │                         │  ┌────────────┐  │
│  │  Harness  │  │                         │  │  Tool Impl │  │
│  │ (9-stage) │  │                         │  │            │  │
│  └───────────┘  │                         │  └────────────┘  │
└─────────────────┘                         └──────────────────┘
       │
       ▼
┌─────────────────┐
│     Kafka       │
│   (raw-feed)    │
└─────────────────┘
```

## Plugin Structure

Each plugin is a self-contained Go project with:

```
plugins/<name>/
├── manifest.yaml      # Plugin metadata (adapted from OpenClaw SKILL.md)
├── main.go            # MCP server implementation
├── go.mod             # Go module
├── Dockerfile         # Container build
├── config.yaml        # Configuration template
└── README.md          # Documentation
```

## Manifest Format (`manifest.yaml`)

Adapted from OpenClaw's `SKILL.md` frontmatter:

```yaml
name: websearch
description: "Web search and page fetch via Brave Search API + readability"
version: "1.0.0"
metadata:
  omnig:
    requires_env:
      - BRAVE_API_KEY
    requires_bins: []
    primary_env: "BRAVE_API_KEY"
    kiq_tags:
      - "factual"
      - "research"
      - "osint"
      - "general"
    tenant_isolation: true
    risk_level: "low"
    homepage: "https://github.com/omni-g/aggregator/plugins/websearch"
    emoji: "🔍"
```

### Fields

| Field | Description |
|-------|-------------|
| `name` | Unique plugin identifier (lowercase, hyphens allowed) |
| `description` | Human-readable description |
| `version` | Semantic version |
| `metadata.omnig.requires_env` | Required environment variables |
| `metadata.omnig.requires_bins` | Required CLI binaries |
| `metadata.omnig.primary_env` | Primary credential env var |
| `metadata.omnig.kiq_tags` | KIQ tags for AgenticRouter (factual, news, monitoring, etc.) |
| `metadata.omnig.tenant_isolation` | Whether plugin enforces tenant isolation |
| `metadata.omnig.risk_level` | Harness risk level: `low`, `medium`, `high` |
| `metadata.omnig.homepage` | Documentation URL |
| `metadata.omnig.emoji` | Display emoji |

## Plugin Configuration (`plugins.yaml`)

The Aggregator reads `plugins.yaml` at startup:

```yaml
plugins:
  - name: websearch
    enabled: true
    manifest: "./plugins/websearch/manifest.yaml"
    mcp_url: "http://websearch:8080/mcp"
    description: "Web search and page fetch via Brave Search + readability"
    headers:
      Authorization: "Bearer ${WEBSEARCH_TOKEN:-}"

  - name: newsearch
    enabled: true
    manifest: "./plugins/newsearch/manifest.yaml"
    mcp_url: "http://newsearch:8080/mcp"
    description: "News headlines, article read, and news search via RSS aggregation"
    headers: {}
```

### Fields

| Field | Description |
|-------|-------------|
| `name` | Must match manifest `name` |
| `enabled` | Whether to load this plugin |
| `manifest` | Path to manifest.yaml (relative to aggregator root) |
| `mcp_url` | MCP endpoint URL (HTTP+SSE) |
| `headers` | Optional headers for MCP requests |
| `description` | Human-readable description |

Environment variable expansion uses `${VAR:-default}` syntax.

## Building a Plugin

### 1. Create Plugin Directory

```bash
mkdir -p services/aggregator/plugins/myplugin
cd services/aggregator/plugins/myplugin
```

### 2. Create `manifest.yaml`

```yaml
name: myplugin
description: "My custom plugin for Omni-G"
version: "1.0.0"
metadata:
  omnig:
    requires_env:
      - MY_API_KEY
    requires_bins: []
    primary_env: "MY_API_KEY"
    kiq_tags:
      - "custom"
    tenant_isolation: true
    risk_level: "low"
    homepage: ""
```

### 3. Create `go.mod`

```go
module github.com/omni-g/aggregator/plugins/myplugin

go 1.23

require (
	github.com/omni-g/aggregator v0.0.0
)

replace github.com/omni-g/aggregator => ../../

require (
	github.com/rs/zerolog v1.32.0
	gopkg.in/yaml.v3 v3.0.1
)
```

### 4. Create `main.go`

```go
package main

import (
	"context"
	"encoding/json"
	"os"

	"github.com/omni-g/aggregator/internal/mcp"
	"github.com/omni-g/aggregator/pkg/harness"
	"github.com/omni-g/aggregator/pkg/plugin"
)

func main() {
	apiKey := os.Getenv("MY_API_KEY")
	if apiKey == "" {
		// Handle missing API key
	}

	server := plugin.NewServer(plugin.ServerConfig{
		Name:        "myplugin",
		Version:     "1.0.0",
		Description: "My custom plugin for Omni-G",
		Port:        8080,
	})

	server.RegisterTool(&plugin.Tool{
		Name:        "myplugin_action",
		Description: "Perform a custom action",
		Version:     "1.0.0",
		Risk:        harness.RiskLow,
		InputSchema: json.RawMessage(`{
			"type": "object",
			"properties": {
				"param": {"type": "string", "description": "Input parameter"}
			},
			"required": ["param"]
		}`),
		Handler: func(ctx context.Context, args map[string]any) (<-chan mcp.ContentBlock, error) {
			param := args["param"].(string)

			// Implement your logic here
			result := map[string]any{
				"param": param,
				"output": "Result from myplugin",
			}

			data, _ := json.Marshal(result)
			ch := make(chan mcp.ContentBlock, 1)
			ch <- mcp.ContentBlock{Type: mcp.ContentTypeText, Text: string(data)}
			close(ch)
			return ch, nil
		},
	})

	if err := server.Run(); err != nil {
		os.Stderr.WriteString("Server error: " + err.Error() + "\n")
		os.Exit(1)
	}
}
```

### 5. Create `Dockerfile`

```dockerfile
# Build stage
FROM golang:1.23-alpine AS builder

WORKDIR /app
RUN apk add --no-cache git

COPY go.mod go.sum ./
RUN go mod download

COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -o myplugin .

# Runtime stage
FROM alpine:3.20
WORKDIR /app
RUN apk add --no-cache ca-certificates
RUN adduser -D -g '' appuser
COPY --from=builder /app/myplugin .
COPY config.yaml .
RUN chown -R appuser:appuser /app
USER appuser
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:8080/health || exit 1
ENTRYPOINT ["./myplugin"]
```

### 6. Create `config.yaml`

```yaml
# myplugin Configuration
port: 8080
mcp_path: "/mcp"
log_level: "info"

# Plugin-specific
my_api_key: "${MY_API_KEY:-}"
timeout_seconds: 30
```

### 7. Build and Test

```bash
# Local build
go mod tidy
go build -o myplugin .
./myplugin

# Docker build
docker build -t myplugin:latest .
docker run -p 8080:8080 -e MY_API_KEY=xxx myplugin:latest
```

### 8. Register with Aggregator

Add to `plugins.yaml`:

```yaml
plugins:
  - name: myplugin
    enabled: true
    manifest: "./plugins/myplugin/manifest.yaml"
    mcp_url: "http://myplugin:8080/mcp"
    headers:
      Authorization: "Bearer ${MYPLUGIN_TOKEN:-}"
```

Add to `docker-compose.yml`:

```yaml
services:
  myplugin:
    build: ./services/aggregator/plugins/myplugin
    container_name: omni-g-myplugin
    ports:
      - "8083:8080"
    environment:
      MY_API_KEY: ${MY_API_KEY:-}
      LOG_LEVEL: ${MYPLUGIN_LOG_LEVEL:-info}
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 15s
      timeout: 5s
      retries: 5
      start_period: 10s
    profiles:
      - ai
      - services
      - all
    networks:
      - omni-g
```

Update aggregator `depends_on`:

```yaml
aggregator:
  depends_on:
    myplugin:
      condition: service_healthy
```

## Plugin SDK Reference

### `plugin.Server`

```go
server := plugin.NewServer(plugin.ServerConfig{
    Name:        "myplugin",
    Version:     "1.0.0",
    Description: "Description",
    Port:        8080,
    MCPPath:     "/mcp",  // optional, default: "/mcp"
})
```

### `plugin.Tool`

```go
server.RegisterTool(&plugin.Tool{
    Name:        "tool_name",
    Description: "Human-readable description",
    Version:     "1.0.0",
    Risk:        harness.RiskLow,  // or RiskMedium, RiskHigh
    InputSchema: json.RawMessage(`{...}`),  // JSON Schema
    Handler: func(ctx context.Context, args map[string]any) (<-chan mcp.ContentBlock, error) {
        // Return channel of ContentBlocks
        ch := make(chan mcp.ContentBlock, 1)
        ch <- mcp.ContentBlock{Type: mcp.ContentTypeText, Text: "result"}
        close(ch)
        return ch, nil
    },
})
```

### `mcp.ContentBlock`

```go
// Text content
mcp.ContentBlock{Type: mcp.ContentTypeText, Text: "text content"}

// Image content (base64)
mcp.ContentBlock{Type: mcp.ContentTypeImage, Text: "base64data"}
```

### Running the Server

```go
if err := server.Run(); err != nil {
    log.Error().Err(err).Msg("Server error")
    os.Exit(1)
}
```

The server handles:
- `POST /mcp/tools/list` — Returns registered tools
- `POST /mcp/tools/call` — Executes a tool (streams via SSE)
- `GET /health` — Health check endpoint

## Harness Integration

All plugin tools automatically go through the **9-stage Harness**:

1. **Register** — Validate tool descriptor (at startup)
2. **Advertise** — Expose to AgenticRouter
3. **Select** — Look up tool by name
4. **Validate** — Check arguments against InputSchema
5. **Permission** — Enforce tenant access control
6. **Execute** — Run tool with circuit breaker
7. **Observe** — Emit Prometheus metrics
8. **Normalize** — Convert to RawEvent envelope
9. **ReturnLoop** — Return InvokeResult

## AgenticRouter Integration

The AgenticRouter uses plugin `kiq_tags` to intelligently select tools:

| KIQ Tag | Typical Tools |
|---------|---------------|
| `factual` | web_search |
| `research` | web_search, web_fetch |
| `news` | news_headlines, news_search |
| `current_events` | news_search |
| `monitoring` | news_headlines |
| `location` | weather_forecast, places_search |
| `markets` | markets_list |

## Testing Plugins

### Unit Tests

```go
func TestMyPluginTool(t *testing.T) {
    server := plugin.NewServer(plugin.ServerConfig{Name: "test", Port: 0})
    // Register tool...

    // Test via MCP client
    client := mcp.NewClient("http://localhost:8080/mcp", nil)
    tools, _ := client.ListTools(context.Background())
    // Assert tools...
}
```

### Integration Test

```bash
# Start plugin
docker run -d -p 8080:8080 -e MY_API_KEY=xxx myplugin:latest

# Test MCP endpoints
curl -X POST http://localhost:8080/mcp/tools/list \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'

curl -X POST http://localhost:8080/mcp/tools/call \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"myplugin_action","arguments":{"param":"test"}}}'
```

## Existing Plugins

### websearch
- **Tools**: `web_search`, `web_fetch`
- **Provider**: Brave Search API
- **Requires**: `BRAVE_API_KEY`
- **KIQ Tags**: factual, research, osint, general

### newsearch
- **Tools**: `news_headlines`, `news_read`, `news_search`
- **Provider**: RSS aggregation (BBC, NYT, Reuters, Guardian, etc.)
- **Requires**: None
- **KIQ Tags**: news, current_events, monitoring, breaking

## Adding New Plugins

1. Create plugin directory under `services/aggregator/plugins/`
2. Implement manifest.yaml, main.go, go.mod, Dockerfile, config.yaml
3. Build and test locally
4. Add to `plugins.yaml`
5. Add service to `docker-compose.yml`
6. Update aggregator `depends_on`
7. Rebuild and deploy

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Plugin not discovered | Check `plugins.yaml` path, `enabled: true`, manifest exists |
| MCP connection failed | Verify `mcp_url`, plugin health check passes, network connectivity |
| Tool not in Harness | Check plugin RegisterTool calls, Harness.Register errors in logs |
| Permission denied | Verify tenant_id in Permission, tool in AllowedTools |
| Circuit breaker open | Check tool error rate, HarnessCircuitBreakerThreshold config |

## References

- [OpenClaw SKILL.md Format](https://github.com/openclaw/clawhub/blob/main/docs/skill-format.md)
- [MCP Specification](https://modelcontextprotocol.io/)
- [Omni-G Harness](pkg/harness/)
- [Omni-G V2 Architecture](docs/V2/ARCHITECTURE.md)
