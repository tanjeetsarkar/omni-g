package mcp_test

import (
	"context"
	"encoding/json"
	"fmt"
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
		json.NewEncoder(w).Encode(resp)
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
		json.NewEncoder(w).Encode(resp)
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

// ─── CallTool (SSE) ──────────────────────────────────────────────────────────

func TestClient_CallTool_SSEStream(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		assert.Equal(t, "/sse", r.URL.Path)
		assert.Equal(t, "text/event-stream", r.Header.Get("Accept"))

		w.Header().Set("Content-Type", "text/event-stream")
		w.WriteHeader(http.StatusOK)

		flusher, ok := w.(http.Flusher)
		require.True(t, ok)

		block, _ := json.Marshal(mcp.ContentBlock{Type: mcp.ContentTypeText, Text: "hello"})
		fmt.Fprintf(w, "data: %s\n\n", block)
		flusher.Flush()

		fmt.Fprintf(w, "data: [DONE]\n\n")
		flusher.Flush()
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

func TestClient_CallTool_ContextCancel(t *testing.T) {
	started := make(chan struct{})

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		w.WriteHeader(http.StatusOK)
		// Flush headers immediately so the client's Do() returns and we can
		// observe the context cancellation on the body reader.
		w.(http.Flusher).Flush()
		close(started)
		// Keep connection open until the client cancels.
		<-r.Context().Done()
	}))
	defer srv.Close()

	ctx, cancel := context.WithCancel(context.Background())
	c := mcp.NewClient(srv.URL)
	ch, err := c.CallTool(ctx, "echo", nil)
	require.NoError(t, err)

	<-started
	cancel()

	// drain channel — should close without blocking
	timeout := time.After(2 * time.Second)
	for {
		select {
		case _, ok := <-ch:
			if !ok {
				return
			}
		case <-timeout:
			t.Fatal("channel not closed after context cancel")
		}
	}
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
