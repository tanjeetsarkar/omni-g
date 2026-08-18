// Package plugin provides the SDK for building Omni-G MCP server plugins.
// Plugins implement tools that register with the Aggregator's Harness via MCP.
package plugin

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/omni-g/aggregator/internal/mcp"
	"github.com/omni-g/aggregator/pkg/harness"
	"github.com/rs/zerolog"
	"github.com/rs/zerolog/log"
)

// Tool defines a single capability that a plugin exposes via MCP.
// Plugins create Tool instances and register them with the Server.
type Tool struct {
	// Name is the unique tool identifier (e.g., "web_search")
	Name string
	// Description is a human-readable description for the AgenticRouter
	Description string
	// Version is the tool version (semver)
	Version string
	// Risk is the Harness risk level: low, medium, high
	Risk harness.RiskLevel
	// InputSchema is the JSON Schema for tool arguments
	InputSchema json.RawMessage
	// Handler is the function that executes the tool
	Handler func(ctx context.Context, args map[string]any) (<-chan mcp.ContentBlock, error)
}

// Server is an embeddable MCP server for plugins.
// It handles tool registration, MCP protocol, and HTTP+SSE transport.
type Server struct {
	name        string
	version     string
	description string
	tools       map[string]*Tool
	mux         *http.ServeMux
	server      *http.Server
	logger      zerolog.Logger
}

// ServerConfig configures the plugin server.
type ServerConfig struct {
	// Name is the plugin name (e.g., "websearch")
	Name string
	// Version is the plugin version
	Version string
	// Description is a human-readable description
	Description string
	// Port is the HTTP port to listen on (default: 8080)
	Port int
	// MCPPath is the MCP endpoint path (default: "/mcp")
	MCPPath string
}

// NewServer creates a new plugin server with the given config.
func NewServer(cfg ServerConfig) *Server {
	if cfg.Port == 0 {
		cfg.Port = 8080
	}
	if cfg.MCPPath == "" {
		cfg.MCPPath = "/mcp"
	}

	logger := log.With().Str("plugin", cfg.Name).Logger()

	s := &Server{
		name:        cfg.Name,
		version:     cfg.Version,
		description: cfg.Description,
		tools:       make(map[string]*Tool),
		mux:         http.NewServeMux(),
		logger:      logger,
	}

	// Register MCP endpoints
	s.mux.HandleFunc(cfg.MCPPath+"/tools/list", s.handleListTools)
	s.mux.HandleFunc(cfg.MCPPath+"/tools/call", s.handleCallTool)
	s.mux.HandleFunc("/health", s.handleHealth)

	s.server = &http.Server{
		Addr:    fmt.Sprintf(":%d", cfg.Port),
		Handler: s.mux,
	}

	return s
}

// RegisterTool adds a tool to the server.
func (s *Server) RegisterTool(tool *Tool) error {
	if tool.Name == "" {
		return fmt.Errorf("tool name is required")
	}
	if tool.Handler == nil {
		return fmt.Errorf("tool %q: handler is required", tool.Name)
	}
	if _, exists := s.tools[tool.Name]; exists {
		return fmt.Errorf("tool %q already registered", tool.Name)
	}

	// Set defaults
	if tool.Version == "" {
		tool.Version = "1.0.0"
	}
	if tool.Risk == "" {
		tool.Risk = harness.RiskLow
	}

	s.tools[tool.Name] = tool
	s.logger.Info().Str("tool", tool.Name).Msg("plugin: tool registered")
	return nil
}

// Run starts the HTTP server and blocks until shutdown signal.
func (s *Server) Run() error {
	// Start server in background
	go func() {
		s.logger.Info().Str("addr", s.server.Addr).Msg("plugin: starting MCP server")
		if err := s.server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			s.logger.Error().Err(err).Msg("plugin: server error")
		}
	}()

	// Wait for shutdown signal
	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)
	<-sigCh

	s.logger.Info().Msg("plugin: shutdown signal received")

	// Graceful shutdown
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	return s.server.Shutdown(ctx)
}

// handleListTools handles the MCP tools/list method.
func (s *Server) handleListTools(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var req mcp.JSONRPCRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		s.writeError(w, req.ID, mcp.ErrInvalidRequest, "invalid request")
		return
	}

	tools := make([]mcp.Tool, 0, len(s.tools))
	for _, t := range s.tools {
		tools = append(tools, mcp.Tool{
			Name:        t.Name,
			Description: t.Description,
			Version:     t.Version,
			InputSchema: t.InputSchema,
		})
	}

	result := mcp.ToolsListResult{Tools: tools}
	s.writeResult(w, req.ID, result)
}

// handleCallTool handles the MCP tools/call method.
func (s *Server) handleCallTool(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var req mcp.JSONRPCRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		s.writeError(w, req.ID, mcp.ErrInvalidRequest, "invalid request")
		return
	}

	var params mcp.ToolCallParams
	if err := json.Unmarshal(req.Params, &params); err != nil {
		s.writeError(w, req.ID, mcp.ErrInvalidParams, "invalid tool call params")
		return
	}

	tool, ok := s.tools[params.Name]
	if !ok {
		s.writeError(w, req.ID, mcp.ErrMethodNotFound, fmt.Sprintf("tool %q not found", params.Name))
		return
	}

	// Execute the tool
	ch, err := tool.Handler(r.Context(), params.Arguments)
	if err != nil {
		s.writeError(w, req.ID, mcp.ErrInternal, fmt.Sprintf("tool execution failed: %v", err))
		return
	}

	// Stream results via SSE
	s.streamResults(w, req.ID, ch)
}

// streamResults streams ContentBlocks as SSE events.
func (s *Server) streamResults(w http.ResponseWriter, id any, ch <-chan mcp.ContentBlock) {
	flusher, ok := w.(http.Flusher)
	if !ok {
		s.logger.Error().Msg("plugin: response writer does not support flushing")
		return
	}

	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")

	// Send initial event
	fmt.Fprintf(w, "id: %v\n", id)
	fmt.Fprintf(w, "event: start\n\n")
	flusher.Flush()

	for block := range ch {
		data, _ := json.Marshal(block)
		fmt.Fprintf(w, "id: %v\n", id)
		fmt.Fprintf(w, "event: message\n")
		fmt.Fprintf(w, "data: %s\n\n", data)
		flusher.Flush()
	}

	// Send completion event
	result := mcp.ToolCallResult{Content: []mcp.ContentBlock{}}
	data, _ := json.Marshal(result)
	fmt.Fprintf(w, "id: %v\n", id)
	fmt.Fprintf(w, "event: end\n")
	fmt.Fprintf(w, "data: %s\n\n", data)
	flusher.Flush()
}

// handleHealth handles the health check endpoint.
func (s *Server) handleHealth(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]any{
		"status":  "healthy",
		"plugin":  s.name,
		"version": s.version,
		"tools":   len(s.tools),
	})
}

// writeResult writes a successful JSON-RPC response.
func (s *Server) writeResult(w http.ResponseWriter, id any, result any) {
	resp := mcp.JSONRPCResponse{
		JSONRPC: "2.0",
		ID:      id,
		Result:  mustMarshal(result),
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(resp)
}

// writeError writes a JSON-RPC error response.
func (s *Server) writeError(w http.ResponseWriter, id any, code int, message string) {
	resp := mcp.JSONRPCResponse{
		JSONRPC: "2.0",
		ID:      id,
		Error: &mcp.JSONRPCError{
			Code:    code,
			Message: message,
		},
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK) // JSON-RPC always returns 200
	json.NewEncoder(w).Encode(resp)
}

// mustMarshal marshals v to JSON or panics.
func mustMarshal(v any) json.RawMessage {
	data, err := json.Marshal(v)
	if err != nil {
		panic(fmt.Sprintf("plugin: marshal result: %v", err))
	}
	return data
}

// Manifest generates a plugin manifest.yaml from the server's registered tools.
// This can be called at build time to generate the manifest file.
func (s *Server) Manifest() string {
	// This is a simplified manifest generator; in practice you'd use a template
	return fmt.Sprintf(`name: %s
description: %s
version: %s
metadata:
  omnig:
    requires_env: []
    requires_bins: []
    primary_env: ""
    kiq_tags: []
    tenant_isolation: true
    risk_level: "low"
    homepage: ""
`, s.name, s.description, s.version)
}
