package mcp

// Package mcp implements the Model Context Protocol (MCP) over HTTP + SSE.
// It supports JSON-RPC 2.0 as the message format and Server-Sent Events for
// streaming tool-call responses.

import "encoding/json"

// ─── JSON-RPC 2.0 envelope ──────────────────────────────────────────────────

// JSONRPCRequest is the standard JSON-RPC 2.0 request object.
type JSONRPCRequest struct {
	JSONRPC string          `json:"jsonrpc"`
	ID      any             `json:"id"`
	Method  string          `json:"method"`
	Params  json.RawMessage `json:"params,omitempty"`
}

// JSONRPCResponse is the standard JSON-RPC 2.0 response object.
type JSONRPCResponse struct {
	JSONRPC string          `json:"jsonrpc"`
	ID      any             `json:"id"`
	Result  json.RawMessage `json:"result,omitempty"`
	Error   *JSONRPCError   `json:"error,omitempty"`
}

// JSONRPCError represents a JSON-RPC 2.0 error object.
type JSONRPCError struct {
	Code    int    `json:"code"`
	Message string `json:"message"`
}

// Standard JSON-RPC error codes.
const (
	ErrParseError     = -32700
	ErrInvalidRequest = -32600
	ErrMethodNotFound = -32601
	ErrInvalidParams  = -32602
	ErrInternal       = -32603
)

// ─── MCP protocol objects ────────────────────────────────────────────────────

// Tool describes a capability exposed by an MCP plugin server.
type Tool struct {
	Name        string          `json:"name"`
	Description string          `json:"description"`
	InputSchema json.RawMessage `json:"inputSchema,omitempty"`
}

// ToolsListResult is the result payload for the "tools/list" method.
type ToolsListResult struct {
	Tools []Tool `json:"tools"`
}

// ToolCallParams is the params payload for a "tools/call" request.
type ToolCallParams struct {
	Name      string         `json:"name"`
	Arguments map[string]any `json:"arguments,omitempty"`
}

// ContentType enumerates the types of content blocks in a tool result.
type ContentType string

const (
	ContentTypeText  ContentType = "text"
	ContentTypeImage ContentType = "image"
)

// ContentBlock is a single item in a tool-call result stream.
type ContentBlock struct {
	Type ContentType `json:"type"`
	Text string      `json:"text,omitempty"`
}

// ToolCallResult is the final (non-streaming) result of a "tools/call" method.
type ToolCallResult struct {
	Content []ContentBlock `json:"content"`
	IsError bool           `json:"isError,omitempty"`
}
