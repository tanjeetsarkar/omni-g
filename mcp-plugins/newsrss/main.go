package main

import (
	"encoding/json"
	"encoding/xml"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/url"
	"os"
	"strings"
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

// ─── RSS types ────────────────────────────────────────────────────────────────

type rssItem struct {
	Title       string `xml:"title"`
	Link        string `xml:"link"`
	Description string `xml:"description"`
	PubDate     string `xml:"pubDate"`
}

type rssChannel struct {
	Items []rssItem `xml:"item"`
}

type rssFeed struct {
	Channel rssChannel `xml:"channel"`
}

// ─── tool registry ────────────────────────────────────────────────────────────

var registeredTools = []tool{
	{
		Name:        "search_news",
		Description: "Searches Google News RSS for recent articles about a topic or entity.",
		InputSchema: json.RawMessage(`{
			"type": "object",
			"properties": {
				"query": {"type": "string", "description": "Search query for news articles"}
			},
			"required": ["query"]
		}`),
	},
}

// ─── RSS fetching ────────────────────────────────────────────────────────────

var httpClient = &http.Client{Timeout: 15 * time.Second}

// googleNewsRSSURL returns the configurable Google News RSS URL.
// Override via GOOGLE_NEWS_RSS_URL env var for rate-limit workarounds.
func googleNewsRSSURL(query string) string {
	base := os.Getenv("GOOGLE_NEWS_RSS_URL")
	if base == "" {
		base = "https://news.google.com/rss/search"
	}
	params := url.Values{}
	params.Set("q", query)
	params.Set("hl", "en-US")
	params.Set("gl", "US")
	params.Set("ceid", "US:en")
	return base + "?" + params.Encode()
}

func fetchNewsRSS(query string) ([]rssItem, error) {
	feedURL := googleNewsRSSURL(query)
	req, err := http.NewRequest(http.MethodGet, feedURL, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("User-Agent", "omni-g-mcp-newsrss/1.0 (https://github.com/omni-g)")

	resp, err := httpClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("Google News RSS HTTP %d", resp.StatusCode)
	}

	raw, err := io.ReadAll(io.LimitReader(resp.Body, 512*1024))
	if err != nil {
		return nil, err
	}

	var feed rssFeed
	if err := xml.Unmarshal(raw, &feed); err != nil {
		return nil, fmt.Errorf("parse RSS: %w", err)
	}

	items := feed.Channel.Items
	if len(items) > 10 {
		items = items[:10]
	}
	return items, nil
}

// stripHTML removes basic HTML tags from description text.
func stripHTML(s string) string {
	var b strings.Builder
	inTag := false
	for _, r := range s {
		switch {
		case r == '<':
			inTag = true
		case r == '>':
			inTag = false
		case !inTag:
			b.WriteRune(r)
		}
	}
	return strings.TrimSpace(b.String())
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

	items, err := fetchNewsRSS(query)
	if err != nil {
		log.Printf("news RSS fetch error: %v", err)
		fmt.Fprintf(w, "data: [DONE]\n\n")
		flusher.Flush()
		return
	}

	for _, item := range items {
		text := fmt.Sprintf("NEWS: %s\n%s\nSOURCE: %s",
			item.Title,
			stripHTML(item.Description),
			item.Link,
		)
		payload := map[string]any{
			"text":        text,
			"source_type": "news",
			"source":      "google-news-rss",
			"query":       query,
			"pub_date":    item.PubDate,
		}
		payloadJSON, _ := json.Marshal(payload)
		block := contentBlock{Type: "text", Text: string(payloadJSON)}
		blockJSON, _ := json.Marshal(block)
		fmt.Fprintf(w, "data: %s\n\n", blockJSON)
		flusher.Flush()
	}

	fmt.Fprintf(w, "data: [DONE]\n\n")
	flusher.Flush()
}

func handleHealth(w http.ResponseWriter, _ *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	fmt.Fprintf(w, `{"status":"ok","service":"mcp-newsrss"}`)
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
	w.WriteHeader(http.StatusOK)
	json.NewEncoder(w).Encode(resp) //nolint:errcheck
}

// ─── main ────────────────────────────────────────────────────────────────────

func main() {
	port := os.Getenv("PORT")
	if port == "" {
		port = "8093"
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

	log.Printf("mcp-newsrss plugin listening on :%s", port)
	if err := srv.ListenAndServe(); err != nil {
		log.Fatalf("server error: %v", err)
	}
}
