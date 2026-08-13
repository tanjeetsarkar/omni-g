package registry

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"testing"

	"github.com/omni-g/aggregator/pkg/harness"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// fakeMCPServer spins up an HTTP server that responds to MCP tools/list and
// tools/call requests, mimicking a mu server.
func fakeMCPServer(t *testing.T, tools []map[string]any) *httptest.Server {
	t.Helper()

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// tools/list returns the tools array.
		var req struct {
			JSONRPC string `json:"jsonrpc"`
			ID      int    `json:"id"`
			Method  string `json:"method"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			t.Logf("fake MCP server: bad request: %v", err)
			w.WriteHeader(http.StatusBadRequest)
			return
		}

		switch req.Method {
		case "tools/list":
			w.Header().Set("Content-Type", "application/json")
			json.NewEncoder(w).Encode(map[string]any{
				"jsonrpc": "2.0",
				"id":      req.ID,
				"result":  map[string]any{"tools": tools},
			})
		case "tools/call":
			// JSON-RPC response with one text block (mu's actual transport).
			result, _ := json.Marshal(map[string]any{
				"content": []map[string]any{{"type": "text", "text": `{"result":"ok"}`}},
			})
			w.Header().Set("Content-Type", "application/json")
			json.NewEncoder(w).Encode(map[string]any{
				"jsonrpc": "2.0",
				"id":      req.ID,
				"result":  json.RawMessage(result),
			})
		default:
			w.WriteHeader(http.StatusMethodNotAllowed)
		}
	}))

	t.Cleanup(srv.Close)
	return srv
}

func TestRegistryConfigLoad(t *testing.T) {
	// Write a temp config file.
	path := t.TempDir() + "/tools.yaml"
	content := `mcp_servers:
  - name: mu
    url: "http://localhost:8080/mcp"
    enabled: true
    description: "test server"
    tool_filter:
      - web_search
  - name: other
    url: "http://localhost:9999/mcp"
    enabled: false
    tool_filter: []
`
	require.NoError(t, os.WriteFile(path, []byte(content), 0644))

	cfg, err := loadConfig(path)
	require.NoError(t, err)
	assert.Len(t, cfg.MCPServers, 2)
	assert.Equal(t, "mu", cfg.MCPServers[0].Name)
	assert.True(t, cfg.MCPServers[0].Enabled)
	assert.Equal(t, []string{"web_search"}, cfg.MCPServers[0].ToolFilter)
	assert.False(t, cfg.MCPServers[1].Enabled)
}

func TestRegistryMissingConfig(t *testing.T) {
	cfg, err := loadConfig("/nonexistent/path/tools.yaml")
	assert.NoError(t, err)
	assert.Len(t, cfg.MCPServers, 0, "missing config → empty registry, no error")
}

func TestExpandEnvWithDefaults(t *testing.T) {
	t.Setenv("MU_MCP_URL", "http://mu:8080/mcp")
	t.Setenv("MU_ENABLED", "true")
	// DELIBERATELY not set: MU_UNSET, MU_EMPTY
	t.Setenv("MU_EMPTY", "")

	tests := []struct {
		name string
		in   string
		want string
	}{
		{"set var uses value", "${MU_MCP_URL}", "http://mu:8080/mcp"},
		{"set var with default uses value", "${MU_MCP_URL:-http://localhost:8080/mcp}", "http://mu:8080/mcp"},
		{"unset var with default uses default", "${MU_UNSET:-http://localhost:8080/mcp}", "http://localhost:8080/mcp"},
		{"empty var with default uses default", "${MU_EMPTY:-true}", "true"},
		{"unset var no default becomes empty", "${MU_UNSET}", ""},
		{"bare var", "$MU_MCP_URL", "http://mu:8080/mcp"},
		{"mixed literal and var", "http://${MU_UNSET:-mu:8080}/mcp", "http://mu:8080/mcp"},
		{"no vars unchanged", "plain text", "plain text"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			assert.Equal(t, tt.want, expandEnvWithDefaults(tt.in))
		})
	}
}

func TestRegistryConfigLoadWithEnvDefaults(t *testing.T) {
	// Reproduce the exact tools.yaml shape that previously broke:
	// os.ExpandEnv silently emptied ${MU_MCP_URL:-...} and ${MU_ENABLED:-true},
	// disabling the mu server and leaving the harness empty.
	path := t.TempDir() + "/tools.yaml"
	content := `mcp_servers:
  - name: mu
    url: "${MU_MCP_URL:-http://localhost:8080/mcp}"
    enabled: ${MU_ENABLED:-true}
    description: "Micro/Mu"
    tool_filter: []
`
	require.NoError(t, os.WriteFile(path, []byte(content), 0644))

	// Without MU_MCP_URL or MU_ENABLED set, the defaults must win.
	t.Setenv("MU_MCP_URL", "") // explicitly unset → empty → use default
	cfg, err := loadConfig(path)
	require.NoError(t, err)
	require.Len(t, cfg.MCPServers, 1)
	assert.Equal(t, "http://localhost:8080/mcp", cfg.MCPServers[0].URL)
	assert.True(t, cfg.MCPServers[0].Enabled, "enabled must default to true, not empty/false")
}

func TestExpandEnvWithDefaultsSetValue(t *testing.T) {
	t.Setenv("MU_MCP_URL", "http://mu:8080/mcp")
	path := t.TempDir() + "/tools.yaml"
	content := `mcp_servers:
  - name: mu
    url: "${MU_MCP_URL:-http://localhost:8080/mcp}"
    enabled: ${MU_ENABLED:-true}
    tool_filter: []
`
	require.NoError(t, os.WriteFile(path, []byte(content), 0644))
	cfg, err := loadConfig(path)
	require.NoError(t, err)
	require.Len(t, cfg.MCPServers, 1)
	assert.Equal(t, "http://mu:8080/mcp", cfg.MCPServers[0].URL)
	assert.True(t, cfg.MCPServers[0].Enabled)
}

func TestRegistryRegisterServer(t *testing.T) {
	tools := []map[string]any{
		{
			"name":        "web_search",
			"description": "Search the web",
			"inputSchema": map[string]any{
				"type":       "object",
				"properties": map[string]any{"query": map[string]any{"type": "string"}},
			},
		},
		{
			"name":        "news_search",
			"description": "Search news",
			"inputSchema": map[string]any{
				"type":       "object",
				"properties": map[string]any{"query": map[string]any{"type": "string"}},
			},
		},
	}

	srv := fakeMCPServer(t, tools)
	h := harness.New(harness.DefaultConfig(), nil)

	r := &ToolRegistry{
		cfg: RegistryConfig{
			MCPServers: []MCPServerConfig{
				{Name: "mu", URL: srv.URL, Enabled: true},
			},
		},
		harness: h,
	}

	count, err := r.RegisterAll(context.Background())
	require.NoError(t, err)
	assert.Equal(t, 2, count, "should register both tools")

	// Verify tools are advertised.
	advertised := h.Advertise()
	assert.Len(t, advertised, 2)
}

func TestRegistryToolFilter(t *testing.T) {
	tools := []map[string]any{
		{
			"name":        "web_search",
			"description": "Search the web",
			"inputSchema": map[string]any{
				"type":       "object",
				"properties": map[string]any{"query": map[string]any{"type": "string"}},
			},
		},
		{
			"name":        "weather_forecast",
			"description": "Get weather",
			"inputSchema": map[string]any{
				"type":       "object",
				"properties": map[string]any{"location": map[string]any{"type": "string"}},
			},
		},
	}

	srv := fakeMCPServer(t, tools)
	h := harness.New(harness.DefaultConfig(), nil)

	r := &ToolRegistry{
		cfg: RegistryConfig{
			MCPServers: []MCPServerConfig{
				{
					Name:       "mu",
					URL:        srv.URL,
					Enabled:    true,
					ToolFilter: []string{"web_search"},
				},
			},
		},
		harness: h,
	}

	count, err := r.RegisterAll(context.Background())
	require.NoError(t, err)
	assert.Equal(t, 1, count, "tool_filter should restrict to web_search only")

	advertised := h.Advertise()
	assert.Len(t, advertised, 1)
	assert.Equal(t, "web_search", advertised[0].Name)
}

func TestRegistryConfigLoadWithHeaders(t *testing.T) {
	path := t.TempDir() + "/tools.yaml"
	content := `mcp_servers:
  - name: mu
    url: "http://localhost:8080/mcp"
    enabled: true
    headers:
      Authorization: "Bearer test-token"
      X-Micro-Token: "legacy-token"
`
	require.NoError(t, os.WriteFile(path, []byte(content), 0644))

	cfg, err := loadConfig(path)
	require.NoError(t, err)
	require.Len(t, cfg.MCPServers, 1)
	assert.Equal(t, "Bearer test-token", cfg.MCPServers[0].Headers["Authorization"])
	assert.Equal(t, "legacy-token", cfg.MCPServers[0].Headers["X-Micro-Token"])
}

func TestRegistryConfigLoadWithHeadersEnvExpansion(t *testing.T) {
	t.Setenv("MU_TOKEN", "env-token-123")

	path := t.TempDir() + "/tools.yaml"
	content := `mcp_servers:
  - name: mu
    url: "http://localhost:8080/mcp"
    enabled: true
    headers:
      Authorization: "Bearer ${MU_TOKEN:-}"
`
	require.NoError(t, os.WriteFile(path, []byte(content), 0644))

	cfg, err := loadConfig(path)
	require.NoError(t, err)
	require.Len(t, cfg.MCPServers, 1)
	assert.Equal(t, "Bearer env-token-123", cfg.MCPServers[0].Headers["Authorization"])
}

func TestRegistryConfigLoadWithHeadersEmptyToken(t *testing.T) {
	// When MU_TOKEN is unset, the header value should be "Bearer " (empty token),
	// which the registry skips when building http.Header.
	path := t.TempDir() + "/tools.yaml"
	content := `mcp_servers:
  - name: mu
    url: "http://localhost:8080/mcp"
    enabled: true
    headers:
      Authorization: "Bearer ${MU_TOKEN:-}"
`
	require.NoError(t, os.WriteFile(path, []byte(content), 0644))

	cfg, err := loadConfig(path)
	require.NoError(t, err)
	require.Len(t, cfg.MCPServers, 1)
	// Default is empty string, so the header value is "Bearer ".
	assert.Equal(t, "Bearer ", cfg.MCPServers[0].Headers["Authorization"])
}

func TestRegistryRegisterServerWithHeaders(t *testing.T) {
	tools := []map[string]any{
		{
			"name":        "web_search",
			"description": "Search the web",
		},
	}

	// Create a fake server that asserts the Authorization header is sent.
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		assert.Equal(t, "Bearer test-token-456", r.Header.Get("Authorization"))

		var req struct {
			JSONRPC string `json:"jsonrpc"`
			ID      int    `json:"id"`
			Method  string `json:"method"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			w.WriteHeader(http.StatusBadRequest)
			return
		}

		switch req.Method {
		case "tools/list":
			w.Header().Set("Content-Type", "application/json")
			json.NewEncoder(w).Encode(map[string]any{
				"jsonrpc": "2.0",
				"id":      req.ID,
				"result":  map[string]any{"tools": tools},
			})
		case "tools/call":
			result, _ := json.Marshal(map[string]any{
				"content": []map[string]any{{"type": "text", "text": "ok"}},
			})
			w.Header().Set("Content-Type", "application/json")
			json.NewEncoder(w).Encode(map[string]any{
				"jsonrpc": "2.0",
				"id":      req.ID,
				"result":  json.RawMessage(result),
			})
		default:
			w.WriteHeader(http.StatusMethodNotAllowed)
		}
	}))
	defer srv.Close()

	h := harness.New(harness.DefaultConfig(), nil)

	r := &ToolRegistry{
		cfg: RegistryConfig{
			MCPServers: []MCPServerConfig{
				{
					Name:    "mu",
					URL:     srv.URL,
					Enabled: true,
					Headers: map[string]string{
						"Authorization": "Bearer test-token-456",
					},
				},
			},
		},
		harness: h,
	}

	count, err := r.RegisterAll(context.Background())
	require.NoError(t, err)
	assert.Equal(t, 1, count)

	// Invoke the registered tool — it should also carry the header.
	advertised := h.Advertise()
	require.Len(t, advertised, 1)

	result, err := h.InvokeTool(context.Background(), "web_search", nil,
		harness.Permission{TenantID: "test-tenant"}, "", "test-tenant")
	require.NoError(t, err)
	require.NotNil(t, result)
}
