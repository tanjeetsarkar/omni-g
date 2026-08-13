package mcp_test

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/omni-g/aggregator/internal/mcp"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// ─── ListTools ────────────────────────────────────────────────────────────────

func TestClient_ListTools_Success(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		assert.Equal(t, http.MethodPost, r.Method)
		assert.Equal(t, "application/json", r.Header.Get("Content-Type"))

		var req mcp.JSONRPCRequest
		require.NoError(t, json.NewDecoder(r.Body).Decode(&req))
		assert.Equal(t, "tools/list", req.Method)

		result, _ := json.Marshal(mcp.ToolsListResult{
			Tools: []mcp.Tool{
				{Name: "echo", Description: "Echoes input"},
			},
		})
		resp := mcp.JSONRPCResponse{JSONRPC: "2.0", ID: req.ID, Result: json.RawMessage(result)}
		w.Header().Set("Content-Type", "application/json")
		require.NoError(t, json.NewEncoder(w).Encode(resp))
	}))
	defer srv.Close()

	c := mcp.NewClient(srv.URL)
	tools, err := c.ListTools(context.Background())

	require.NoError(t, err)
	require.Len(t, tools, 1)
	assert.Equal(t, "echo", tools[0].Name)
}

func TestClient_ListTools_RPCError(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		resp := mcp.JSONRPCResponse{
			JSONRPC: "2.0",
			ID:      1,
			Error:   &mcp.JSONRPCError{Code: mcp.ErrMethodNotFound, Message: "unknown method"},
		}
		w.Header().Set("Content-Type", "application/json")
		require.NoError(t, json.NewEncoder(w).Encode(resp))
	}))
	defer srv.Close()

	c := mcp.NewClient(srv.URL)
	_, err := c.ListTools(context.Background())

	require.Error(t, err)
	assert.Contains(t, err.Error(), "unknown method")
}

func TestClient_ListTools_HTTPError(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusServiceUnavailable)
	}))
	defer srv.Close()

	c := mcp.NewClient(srv.URL)
	_, err := c.ListTools(context.Background())

	require.Error(t, err)
	assert.Contains(t, err.Error(), "503")
}

func TestClient_ListTools_Unreachable(t *testing.T) {
	c := mcp.NewClient("http://localhost:1") // nothing listening
	_, err := c.ListTools(context.Background())
	require.Error(t, err)
}

func TestClient_ListTools_SendsHeaders(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		assert.Equal(t, "Bearer test-token-abc", r.Header.Get("Authorization"))
		assert.Equal(t, "micro-legacy-token", r.Header.Get("X-Micro-Token"))

		result, _ := json.Marshal(mcp.ToolsListResult{Tools: []mcp.Tool{}})
		resp := mcp.JSONRPCResponse{JSONRPC: "2.0", ID: 1, Result: json.RawMessage(result)}
		w.Header().Set("Content-Type", "application/json")
		require.NoError(t, json.NewEncoder(w).Encode(resp))
	}))
	defer srv.Close()

	headers := http.Header{
		"Authorization": {"Bearer test-token-abc"},
		"X-Micro-Token": {"micro-legacy-token"},
	}
	c := mcp.NewClientWithHeaders(srv.URL, headers)
	_, err := c.ListTools(context.Background())
	require.NoError(t, err)
}

func TestClient_CallTool_SendsHeaders(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		assert.Equal(t, "Bearer call-token", r.Header.Get("Authorization"))

		// JSON-RPC response with an empty content array.
		result, _ := json.Marshal(mcp.ToolCallResult{})
		resp := mcp.JSONRPCResponse{JSONRPC: "2.0", ID: 2, Result: json.RawMessage(result)}
		w.Header().Set("Content-Type", "application/json")
		require.NoError(t, json.NewEncoder(w).Encode(resp))
	}))
	defer srv.Close()

	headers := http.Header{"Authorization": {"Bearer call-token"}}
	c := mcp.NewClientWithHeaders(srv.URL, headers)
	ch, err := c.CallTool(context.Background(), "test", nil)
	require.NoError(t, err)
	// drain
	for range ch {
	}
}

// ─── CallTool (JSON-RPC over POST) ───────────────────────────────────────────

func TestClient_CallTool_JSONRPC(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// tools/call POSTs to the base URL (no /sse suffix).
		assert.Equal(t, "/", r.URL.Path)
		assert.Equal(t, http.MethodPost, r.Method)
		assert.Equal(t, "application/json", r.Header.Get("Accept"))

		var req mcp.JSONRPCRequest
		require.NoError(t, json.NewDecoder(r.Body).Decode(&req))
		assert.Equal(t, "tools/call", req.Method)

		result, _ := json.Marshal(mcp.ToolCallResult{
			Content: []mcp.ContentBlock{{Type: mcp.ContentTypeText, Text: "hello"}},
		})
		resp := mcp.JSONRPCResponse{JSONRPC: "2.0", ID: req.ID, Result: json.RawMessage(result)}
		w.Header().Set("Content-Type", "application/json")
		require.NoError(t, json.NewEncoder(w).Encode(resp))
	}))
	defer srv.Close()

	c := mcp.NewClient(srv.URL)
	ch, err := c.CallTool(context.Background(), "echo", map[string]any{"msg": "hello"})

	require.NoError(t, err)

	var blocks []mcp.ContentBlock
	for b := range ch {
		blocks = append(blocks, b)
	}

	require.Len(t, blocks, 1)
	assert.Equal(t, mcp.ContentTypeText, blocks[0].Type)
	assert.Equal(t, "hello", blocks[0].Text)
}

func TestClient_CallTool_RPCError(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		resp := mcp.JSONRPCResponse{
			JSONRPC: "2.0",
			ID:      2,
			Error:   &mcp.JSONRPCError{Code: -32000, Message: "Insufficient credits"},
		}
		w.Header().Set("Content-Type", "application/json")
		require.NoError(t, json.NewEncoder(w).Encode(resp))
	}))
	defer srv.Close()

	c := mcp.NewClient(srv.URL)
	_, err := c.CallTool(context.Background(), "priced_tool", nil)

	require.Error(t, err)
	assert.Contains(t, err.Error(), "Insufficient credits")
}

func TestClient_CallTool_IsError(t *testing.T) {
	// mu signals a tool-level failure with result.isError=true and a text
	// block describing the failure. The block is delivered (not converted to
	// a Go error) so the harness circuit breaker does not trip on legitimate
	// tool refusals.
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		result, _ := json.Marshal(mcp.ToolCallResult{
			Content: []mcp.ContentBlock{{Type: mcp.ContentTypeText, Text: "Search query required"}},
			IsError: true,
		})
		resp := mcp.JSONRPCResponse{JSONRPC: "2.0", ID: 2, Result: json.RawMessage(result)}
		w.Header().Set("Content-Type", "application/json")
		require.NoError(t, json.NewEncoder(w).Encode(resp))
	}))
	defer srv.Close()

	c := mcp.NewClient(srv.URL)
	ch, err := c.CallTool(context.Background(), "places_search", nil)

	require.NoError(t, err)
	var blocks []mcp.ContentBlock
	for b := range ch {
		blocks = append(blocks, b)
	}
	require.Len(t, blocks, 1)
	assert.Equal(t, "Search query required", blocks[0].Text)
}

func TestClient_CallTool_ContextCancel(t *testing.T) {
	// With the synchronous JSON-RPC transport, context cancellation aborts
	// the HTTP call and CallTool returns an error (no channel returned).
	done := make(chan struct{})
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// Block until the request is cancelled OR the test finishes, so
		// srv.Close() does not hang on an active connection.
		select {
		case <-r.Context().Done():
		case <-done:
		}
	}))
	defer srv.Close()
	defer close(done)

	ctx, cancel := context.WithCancel(context.Background())
	c := mcp.NewClient(srv.URL)

	// Cancel shortly after issuing the call.
	go func() {
		time.Sleep(50 * time.Millisecond)
		cancel()
	}()

	_, err := c.CallTool(ctx, "echo", nil)
	require.Error(t, err)
}

// ─── Handler ─────────────────────────────────────────────────────────────────

func TestHandler_HandleToolsList_Empty(t *testing.T) {
	h := mcp.NewHandler()
	req := httptest.NewRequest(http.MethodGet, "/mcp/tools", nil)
	rec := httptest.NewRecorder()

	h.HandleToolsList(rec, req)

	assert.Equal(t, http.StatusOK, rec.Code)

	var resp mcp.JSONRPCResponse
	require.NoError(t, json.NewDecoder(rec.Body).Decode(&resp))

	var result mcp.ToolsListResult
	require.NoError(t, json.Unmarshal(resp.Result, &result))
	assert.Empty(t, result.Tools)
}

func TestHandler_HandleToolsList_WithTools(t *testing.T) {
	h := mcp.NewHandler()
	h.RegisterTool(mcp.Tool{Name: "twitter", Description: "Twitter/X feed"})
	h.RegisterTool(mcp.Tool{Name: "shodan", Description: "Shodan host data"})

	req := httptest.NewRequest(http.MethodGet, "/mcp/tools", nil)
	rec := httptest.NewRecorder()

	h.HandleToolsList(rec, req)

	assert.Equal(t, http.StatusOK, rec.Code)

	var resp mcp.JSONRPCResponse
	require.NoError(t, json.NewDecoder(rec.Body).Decode(&resp))

	var result mcp.ToolsListResult
	require.NoError(t, json.Unmarshal(resp.Result, &result))
	assert.Len(t, result.Tools, 2)
	assert.Equal(t, "twitter", result.Tools[0].Name)
}
