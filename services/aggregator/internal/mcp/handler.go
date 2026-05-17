package mcp

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"sync"
)

// Handler serves the aggregator's own MCP discovery endpoint (`GET /mcp/tools`).
// It exposes the list of data sources the aggregator is currently ingesting from,
// allowing upstream agents to discover available tools.
type Handler struct {
	mu       sync.RWMutex
	byPlugin map[string][]Tool // keyed by plugin URL; "__manual__" for RegisterTool entries
}

// NewHandler creates an empty Handler.
func NewHandler() *Handler {
	return &Handler{byPlugin: make(map[string][]Tool)}
}

// RegisterTool adds a tool to the discovery list under the "__manual__" bucket.
// Safe to call from multiple goroutines.
func (h *Handler) RegisterTool(t Tool) {
	h.mu.Lock()
	defer h.mu.Unlock()
	h.byPlugin["__manual__"] = append(h.byPlugin["__manual__"], t)
}

// UpdatePluginTools replaces the registered tools for the given plugin URL.
// Safe to call from multiple goroutines.
func (h *Handler) UpdatePluginTools(pluginURL string, tools []Tool) {
	h.mu.Lock()
	defer h.mu.Unlock()
	h.byPlugin[pluginURL] = tools
}

// DiscoverTools contacts pluginURL, fetches its tools/list, updates the
// handler's registry for that plugin, and returns the discovered tools.
// Intended for initial startup discovery and periodic refresh.
func (h *Handler) DiscoverTools(ctx context.Context, pluginURL string) ([]Tool, error) {
	c := NewClient(pluginURL)
	tools, err := c.ListTools(ctx)
	if err != nil {
		return nil, fmt.Errorf("discover tools from %s: %w", pluginURL, err)
	}
	h.UpdatePluginTools(pluginURL, tools)
	return tools, nil
}

// HandleToolsList serves GET /mcp/tools, returning all registered tools as a
// JSON-RPC 2.0 result envelope so upstream MCP clients can treat this endpoint
// like any other MCP server.
func (h *Handler) HandleToolsList(w http.ResponseWriter, _ *http.Request) {
	h.mu.RLock()
	var tools []Tool
	for _, ts := range h.byPlugin {
		tools = append(tools, ts...)
	}
	h.mu.RUnlock()

	result, err := json.Marshal(ToolsListResult{Tools: tools})
	if err != nil {
		http.Error(w, "internal error", http.StatusInternalServerError)
		return
	}

	resp := JSONRPCResponse{
		JSONRPC: "2.0",
		ID:      nil,
		Result:  json.RawMessage(result),
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	json.NewEncoder(w).Encode(resp) //nolint:errcheck
}
