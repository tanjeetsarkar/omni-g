package main

import (
	"encoding/json"
	"encoding/xml"
	"fmt"
	"io"
	"log"
	"net/http"
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
		Name:        "fetch_reuters_rss",
		Description: "Fetches BBC Technology RSS feed and filters articles matching the query. Falls back to NPR News on error.",
		InputSchema: json.RawMessage(`{
			"type": "object",
			"properties": {
				"query": {"type": "string", "description": "Search term to filter Reuters/AP articles by"}
			},
			"required": ["query"]
		}`),
	},
}

// ─── feed URLs ────────────────────────────────────────────────────────────────

func reutersURL() string {
	if u := os.Getenv("REUTERS_RSS_URL"); u != "" {
		return u
	}
	return "https://feeds.bbci.co.uk/news/technology/rss.xml"
}

func apNewsURL() string {
	if u := os.Getenv("AP_NEWS_RSS_URL"); u != "" {
		return u
	}
	return "https://feeds.npr.org/1001/rss.xml"
}

// ─── RSS fetching ────────────────────────────────────────────────────────────

var httpClient = &http.Client{Timeout: 15 * time.Second}

func fetchRSS(feedURL string) ([]rssItem, error) {
	req, err := http.NewRequest(http.MethodGet, feedURL, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("User-Agent", "omni-g-mcp-reuters/1.0 (https://github.com/omni-g)")

	resp, err := httpClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("RSS feed HTTP %d", resp.StatusCode)
	}

	raw, err := io.ReadAll(io.LimitReader(resp.Body, 512*1024))
	if err != nil {
		return nil, err
	}

	var feed rssFeed
	if err := xml.Unmarshal(raw, &feed); err != nil {
		return nil, fmt.Errorf("parse RSS: %w", err)
	}
	return feed.Channel.Items, nil
}

// filterByQuery returns items whose title or description contains the query
// (case-insensitive). Returns up to 10 matches.
func filterByQuery(items []rssItem, query string) []rssItem {
	q := strings.ToLower(query)
	var matched []rssItem
	for _, item := range items {
		haystack := strings.ToLower(item.Title + " " + item.Description)
		if strings.Contains(haystack, q) {
			matched = append(matched, item)
			if len(matched) >= 10 {
				break
			}
		}
	}
	return matched
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

	// Try BBC Technology, fall back to NPR News.
	items, err := fetchRSS(reutersURL())
	sourceName := "bbc-technology-rss"
	if err != nil {
		log.Printf("BBC Technology RSS fetch error: %v — trying NPR News fallback", err)
		items, err = fetchRSS(apNewsURL())
		sourceName = "npr-rss"
		if err != nil {
			log.Printf("NPR News RSS fallback also failed: %v", err)
			fmt.Fprintf(w, "data: [DONE]\n\n")
			flusher.Flush()
			return
		}
	}

	matched := filterByQuery(items, query)
	if len(matched) == 0 {
		// Return all items if no filter match (query may be a proper noun not in title)
		if len(items) > 5 {
			matched = items[:5]
		} else {
			matched = items
		}
	}

	for _, item := range matched {
		text := fmt.Sprintf("NEWS: %s\n%s\nSOURCE: %s",
			item.Title,
			stripHTML(item.Description),
			item.Link,
		)
		payload := map[string]any{
			"text":        text,
			"source_type": "news",
			"source":      sourceName,
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
	fmt.Fprintf(w, `{"status":"ok","service":"mcp-reuters"}`)
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
		port = "8094"
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

	log.Printf("mcp-reuters plugin listening on :%s", port)
	if err := srv.ListenAndServe(); err != nil {
		log.Fatalf("server error: %v", err)
	}
}
