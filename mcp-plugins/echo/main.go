package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"time"
)

// ─── JSON-RPC types (self-contained, no external deps) ───────────────────────

type rpcRequest struct {
	JSONRPC string          `json:"jsonrpc"`
	ID      any             `json:"id"`
	Method  string          `json:"method"`
	Params  json.RawMessage `json:"params,omitempty"`
}

type rpcResponse struct {
	JSONRPC string          `json:"jsonrpc"`
	ID      any             `json:"id"`
	Result  json.RawMessage `json:"result,omitempty"`
	Error   *rpcError       `json:"error,omitempty"`
}

type rpcError struct {
	Code    int    `json:"code"`
	Message string `json:"message"`
}

type tool struct {
	Name        string          `json:"name"`
	Description string          `json:"description"`
	InputSchema json.RawMessage `json:"inputSchema,omitempty"`
}

type toolCallParams struct {
	Name      string         `json:"name"`
	Arguments map[string]any `json:"arguments,omitempty"`
}

type contentBlock struct {
	Type string `json:"type"`
	Text string `json:"text"`
}

// ─── tool registry ────────────────────────────────────────────────────────────

var registeredTools = []tool{
	{
		Name:        "echo",
		Description: "Echoes the input arguments back as a raw event payload.",
		InputSchema: json.RawMessage(`{
			"type": "object",
			"properties": {
				"source": {"type": "string", "description": "Event source identifier"},
				"payload": {"type": "object", "description": "Arbitrary event payload"}
			},
			"required": ["source", "payload"]
		}`),
	},
}

// ─── handlers ────────────────────────────────────────────────────────────────

func handleRPC(w http.ResponseWriter, r *http.Request) {
	var req rpcRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeRPCError(w, nil, -32700, "parse error")
		return
	}

	switch req.Method {
	case "tools/list":
		result, _ := json.Marshal(map[string]any{"tools": registeredTools})
		writeRPCResult(w, req.ID, json.RawMessage(result))

	default:
		writeRPCError(w, req.ID, -32601, fmt.Sprintf("method not found: %s", req.Method))
	}
}

func handleSSE(w http.ResponseWriter, r *http.Request) {
	var req rpcRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "bad request", http.StatusBadRequest)
		return
	}

	if req.Method != "tools/call" {
		http.Error(w, "only tools/call is supported on /sse", http.StatusBadRequest)
		return
	}

	var params toolCallParams
	if len(req.Params) > 0 {
		json.Unmarshal(req.Params, &params) //nolint:errcheck
	}

	// Build the echo payload.
	// "data" satisfies the validator's requirement for at least one of:
	// text, content, data, url.
	echoSource := params.Arguments["source"]
	if echoSource == nil {
		echoSource = "echo-plugin"
	}
	echoData := params.Arguments["payload"]
	if echoData == nil {
		echoData = map[string]any{}
	}
	echoPayload := map[string]any{
		"source":    echoSource,
		"data":      echoData,
		"echoed_at": time.Now().UTC().Format(time.RFC3339),
	}

	echoText, _ := json.Marshal(echoPayload)
	block := contentBlock{Type: "text", Text: string(echoText)}
	blockJSON, _ := json.Marshal(block)

	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")
	w.WriteHeader(http.StatusOK)

	flusher, ok := w.(http.Flusher)
	if !ok {
		log.Println("ResponseWriter does not support flushing")
		return
	}

	fmt.Fprintf(w, "data: %s\n\n", blockJSON)
	flusher.Flush()

	fmt.Fprintf(w, "data: [DONE]\n\n")
	flusher.Flush()
}

func handleHealth(w http.ResponseWriter, _ *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	fmt.Fprintf(w, `{"status":"ok","service":"mcp-echo"}`)
}

// ─── helpers ─────────────────────────────────────────────────────────────────

func writeRPCResult(w http.ResponseWriter, id any, result json.RawMessage) {
	resp := rpcResponse{JSONRPC: "2.0", ID: id, Result: result}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(resp) //nolint:errcheck
}

func writeRPCError(w http.ResponseWriter, id any, code int, msg string) {
	resp := rpcResponse{
		JSONRPC: "2.0",
		ID:      id,
		Error:   &rpcError{Code: code, Message: msg},
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)    // JSON-RPC errors still return HTTP 200
	json.NewEncoder(w).Encode(resp) //nolint:errcheck
}

// ─── main ────────────────────────────────────────────────────────────────────

func main() {
	port := os.Getenv("PORT")
	if port == "" {
		port = "8090"
	}

	mux := http.NewServeMux()
	mux.HandleFunc("POST /", handleRPC)
	mux.HandleFunc("POST /sse", handleSSE)
	mux.HandleFunc("GET /health", handleHealth)

	srv := &http.Server{
		Addr:         ":" + port,
		Handler:      mux,
		ReadTimeout:  10 * time.Second,
		WriteTimeout: 30 * time.Second,
		IdleTimeout:  120 * time.Second,
	}

	log.Printf("mcp-echo plugin listening on :%s", port)
	if err := srv.ListenAndServe(); err != nil {
		log.Fatalf("server error: %v", err)
	}
}
