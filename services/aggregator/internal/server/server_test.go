package server_test

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/omni-g/aggregator/internal/config"
	"github.com/omni-g/aggregator/internal/mcp"
	"github.com/omni-g/aggregator/internal/server"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func testConfig() *config.Config {
	return &config.Config{
		LogLevel: "disabled",
		HTTPPort: "8080",
	}
}

// newTestServer creates a Server with nil optional dependencies (health-only).
func newTestServer() *server.Server {
	return server.New(testConfig(), nil, nil, nil)
}

func TestHealthEndpoint(t *testing.T) {
	tests := []struct {
		name           string
		path           string
		expectedStatus int
		expectedBody   string
	}{
		{
			name:           "health returns 200",
			path:           "/health",
			expectedStatus: http.StatusOK,
			expectedBody:   "ok",
		},
		{
			name:           "ready returns 200",
			path:           "/ready",
			expectedStatus: http.StatusOK,
			expectedBody:   "ready",
		},
	}

	srv := newTestServer()

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			req := httptest.NewRequest(http.MethodGet, tc.path, nil)
			rec := httptest.NewRecorder()

			srv.ServeHTTP(rec, req)

			assert.Equal(t, tc.expectedStatus, rec.Code)

			var body map[string]string
			require.NoError(t, json.NewDecoder(rec.Body).Decode(&body))
			assert.Equal(t, tc.expectedBody, body["status"])
			assert.Equal(t, "aggregator", body["service"])
		})
	}
}

func TestUnknownRouteReturns404(t *testing.T) {
	srv := newTestServer()

	req := httptest.NewRequest(http.MethodGet, "/unknown", nil)
	rec := httptest.NewRecorder()

	srv.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusNotFound, rec.Code)
}

func TestMCPToolsEndpoint_NoHandler(t *testing.T) {
	srv := newTestServer() // mcpHandler = nil

	req := httptest.NewRequest(http.MethodGet, "/mcp/tools", nil)
	rec := httptest.NewRecorder()

	srv.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusOK, rec.Code)

	var resp mcp.JSONRPCResponse
	require.NoError(t, json.NewDecoder(rec.Body).Decode(&resp))

	var result mcp.ToolsListResult
	require.NoError(t, json.Unmarshal(resp.Result, &result))
	assert.Empty(t, result.Tools)
}

func TestMCPToolsEndpoint_WithRegisteredTools(t *testing.T) {
	h := mcp.NewHandler()
	h.RegisterTool(mcp.Tool{Name: "echo", Description: "echo tool"})

	srv := server.New(testConfig(), nil, nil, h)

	req := httptest.NewRequest(http.MethodGet, "/mcp/tools", nil)
	rec := httptest.NewRecorder()

	srv.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusOK, rec.Code)

	var resp mcp.JSONRPCResponse
	require.NoError(t, json.NewDecoder(rec.Body).Decode(&resp))

	var result mcp.ToolsListResult
	require.NoError(t, json.Unmarshal(resp.Result, &result))
	require.Len(t, result.Tools, 1)
	assert.Equal(t, "echo", result.Tools[0].Name)
}

func TestMetricsEndpoint(t *testing.T) {
	srv := newTestServer()

	req := httptest.NewRequest(http.MethodGet, "/metrics", nil)
	rec := httptest.NewRecorder()

	srv.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusOK, rec.Code)
	assert.Contains(t, rec.Header().Get("Content-Type"), "text/plain")
}
