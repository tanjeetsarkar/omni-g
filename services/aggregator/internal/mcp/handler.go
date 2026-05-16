package mcp

import (
	"encoding/json"
	"net/http"
	"sync"
)

// Handler serves the aggregator's own MCP discovery endpoint (`GET /mcp/tools`).
// It exposes the list of data sources the aggregator is currently ingesting from,
// allowing upstream agents to discover available tools.
type Handler struct {
	mu    sync.RWMutex
	tools []Tool
}

// NewHandler creates an empty Handler.
func NewHandler() *Handler {
	return &Handler{}
}

// RegisterTool adds a tool to the discovery list. Safe to call from multiple
// goroutines.
func (h *Handler) RegisterTool(t Tool) {
	h.mu.Lock()
	defer h.mu.Unlock()
	h.tools = append(h.tools, t)
}

// HandleToolsList serves GET /mcp/tools, returning the registered tools as a
// JSON-RPC 2.0 result envelope so upstream MCP clients can treat this endpoint
// like any other MCP server.
func (h *Handler) HandleToolsList(w http.ResponseWriter, _ *http.Request) {
	h.mu.RLock()
	tools := make([]Tool, len(h.tools))
	copy(tools, h.tools)
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
