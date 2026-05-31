package main

import (
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/url"
	"os"
	"time"
)

// ─── JSON-RPC types ───────────────────────────────────────────────────────────

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

// ─── Wikipedia API response types ────────────────────────────────────────────

type wikiSummary struct {
	Title   string `json:"title"`
	Extract string `json:"extract"`
}

type wikiQueryPage struct {
	Title   string `json:"title"`
	Extract string `json:"extract"`
}

type wikiQueryPages map[string]wikiQueryPage

type wikiQueryResult struct {
	Query struct {
		Pages wikiQueryPages `json:"pages"`
	} `json:"query"`
}

// ─── tool registry ────────────────────────────────────────────────────────────

var registeredTools = []tool{
	{
		Name:        "fetch_wikipedia_article",
		Description: "Fetches a Wikipedia article summary and introduction for an entity or topic.",
		InputSchema: json.RawMessage(`{
			"type": "object",
			"properties": {
				"query": {"type": "string", "description": "Entity name or topic to look up on Wikipedia"}
			},
			"required": ["query"]
		}`),
	},
}

// ─── Wikipedia fetching ───────────────────────────────────────────────────────

var httpClient = &http.Client{Timeout: 15 * time.Second}

func fetchSummary(query string) (string, string, error) {
	apiURL := "https://en.wikipedia.org/api/rest_v1/page/summary/" + url.PathEscape(query)
	req, err := http.NewRequest(http.MethodGet, apiURL, nil)
	if err != nil {
		return "", "", err
	}
	req.Header.Set("User-Agent", "omni-g-mcp-wikipedia/1.0 (https://github.com/omni-g)")

	resp, err := httpClient.Do(req)
	if err != nil {
		return "", "", err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return "", "", fmt.Errorf("wikipedia summary HTTP %d", resp.StatusCode)
	}

	raw, err := io.ReadAll(io.LimitReader(resp.Body, 64*1024))
	if err != nil {
		return "", "", err
	}

	var s wikiSummary
	if err := json.Unmarshal(raw, &s); err != nil {
		return "", "", err
	}
	return s.Title, s.Extract, nil
}

func fetchFullIntro(query string) (string, error) {
	params := url.Values{}
	params.Set("action", "query")
	params.Set("prop", "extracts")
	params.Set("exintro", "true")
	params.Set("explaintext", "true")
	params.Set("titles", query)
	params.Set("format", "json")
	params.Set("redirects", "1")

	apiURL := "https://en.wikipedia.org/w/api.php?" + params.Encode()
	req, err := http.NewRequest(http.MethodGet, apiURL, nil)
	if err != nil {
		return "", err
	}
	req.Header.Set("User-Agent", "omni-g-mcp-wikipedia/1.0 (https://github.com/omni-g)")

	resp, err := httpClient.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("wikipedia query HTTP %d", resp.StatusCode)
	}

	raw, err := io.ReadAll(io.LimitReader(resp.Body, 256*1024))
	if err != nil {
		return "", err
	}

	var result wikiQueryResult
	if err := json.Unmarshal(raw, &result); err != nil {
		return "", err
	}

	for _, page := range result.Query.Pages {
		return page.Extract, nil
	}
	return "", nil
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

	query, _ := params.Arguments["query"].(string)
	if query == "" {
		http.Error(w, "query argument required", http.StatusBadRequest)
		return
	}

	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")
	w.WriteHeader(http.StatusOK)

	flusher, ok := w.(http.Flusher)
	if !ok {
		log.Println("ResponseWriter does not support flushing")
		return
	}

	// Block 1: summary
	title, summary, err := fetchSummary(query)
	if err != nil {
		log.Printf("wikipedia summary fetch error: %v", err)
	} else {
		payload := map[string]any{
			"text":        fmt.Sprintf("WIKIPEDIA SUMMARY: %s\n\n%s", title, summary),
			"source_type": "biographical",
			"source":      "wikipedia",
			"query":       query,
		}
		sendBlock(w, flusher, payload)
	}

	// Block 2: full introduction text
	intro, err := fetchFullIntro(query)
	if err != nil {
		log.Printf("wikipedia intro fetch error: %v", err)
	} else if intro != "" {
		payload := map[string]any{
			"text":        fmt.Sprintf("WIKIPEDIA ARTICLE: %s\n\n%s", query, intro),
			"source_type": "biographical",
			"source":      "wikipedia",
			"query":       query,
		}
		sendBlock(w, flusher, payload)
	}

	fmt.Fprintf(w, "data: [DONE]\n\n")
	flusher.Flush()
}

func handleHealth(w http.ResponseWriter, _ *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	fmt.Fprintf(w, `{"status":"ok","service":"mcp-wikipedia"}`)
}

// ─── helpers ─────────────────────────────────────────────────────────────────

func sendBlock(w http.ResponseWriter, flusher http.Flusher, payload map[string]any) {
	payloadJSON, err := json.Marshal(payload)
	if err != nil {
		return
	}
	block := contentBlock{Type: "text", Text: string(payloadJSON)}
	blockJSON, _ := json.Marshal(block)
	fmt.Fprintf(w, "data: %s\n\n", blockJSON)
	flusher.Flush()
}

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
	w.WriteHeader(http.StatusOK)
	json.NewEncoder(w).Encode(resp) //nolint:errcheck
}

// ─── main ────────────────────────────────────────────────────────────────────

func main() {
	port := os.Getenv("PORT")
	if port == "" {
		port = "8091"
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

	log.Printf("mcp-wikipedia plugin listening on :%s", port)
	if err := srv.ListenAndServe(); err != nil {
		log.Fatalf("server error: %v", err)
	}
}
