package main

import (
	"encoding/json"
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

// ─── Wikidata SPARQL response types ──────────────────────────────────────────

type sparqlBinding struct {
	Type  string `json:"type"`
	Value string `json:"value"`
}

type sparqlResult struct {
	Bindings []map[string]sparqlBinding `json:"bindings"`
}

type sparqlResponse struct {
	Results sparqlResult `json:"results"`
}

// ─── tool registry ────────────────────────────────────────────────────────────

var registeredTools = []tool{
	{
		Name:        "fetch_wikidata_facts",
		Description: "Fetches structured facts from Wikidata for a person or organisation (employer, position, education, birthplace, nationality).",
		InputSchema: json.RawMessage(`{
			"type": "object",
			"properties": {
				"query": {"type": "string", "description": "Entity name to look up on Wikidata (e.g. 'Sundar Pichai')"}
			},
			"required": ["query"]
		}`),
	},
}

// ─── SPARQL query ────────────────────────────────────────────────────────────

// buildSPARQL returns a SPARQL query that searches for an entity by rdfs:label
// and returns structured facts with OPTIONAL clauses to handle missing properties.
func buildSPARQL(entityLabel string) string {
	escaped := strings.ReplaceAll(entityLabel, `"`, `\"`)
	return fmt.Sprintf(`
SELECT ?entity ?entityLabel ?employerLabel ?positionLabel ?educationLabel
       ?birthplaceLabel ?nationalityLabel ?citizenshipLabel ?notableWorkLabel
WHERE {
  ?entity rdfs:label "%s"@en .
  OPTIONAL { ?entity wdt:P108 ?employer . }
  OPTIONAL { ?entity wdt:P39  ?position . }
  OPTIONAL { ?entity wdt:P69  ?education . }
  OPTIONAL { ?entity wdt:P19  ?birthplace . }
  OPTIONAL { ?entity wdt:P27  ?citizenship . }
  OPTIONAL { ?entity wdt:P1343 ?notableWork . }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en" . }
}
LIMIT 20
`, escaped)
}

// ─── Wikidata fetching ───────────────────────────────────────────────────────

var httpClient = &http.Client{Timeout: 20 * time.Second}

func fetchWikidataFacts(entityLabel string) (string, error) {
	sparql := buildSPARQL(entityLabel)

	params := url.Values{}
	params.Set("query", sparql)
	params.Set("format", "json")

	req, err := http.NewRequest(http.MethodGet,
		"https://query.wikidata.org/sparql?"+params.Encode(), nil)
	if err != nil {
		return "", err
	}
	req.Header.Set("User-Agent", "omni-g-mcp-wikidata/1.0 (https://github.com/omni-g)")
	req.Header.Set("Accept", "application/sparql-results+json")

	resp, err := httpClient.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("wikidata SPARQL HTTP %d", resp.StatusCode)
	}

	raw, err := io.ReadAll(io.LimitReader(resp.Body, 256*1024))
	if err != nil {
		return "", err
	}

	var result sparqlResponse
	if err := json.Unmarshal(raw, &result); err != nil {
		return "", err
	}

	return buildFactString(entityLabel, result.Results.Bindings), nil
}

// buildFactString converts SPARQL bindings into a compact fact list.
func buildFactString(label string, bindings []map[string]sparqlBinding) string {
	if len(bindings) == 0 {
		return fmt.Sprintf("WIKIDATA FACTS for %s: no structured facts found", label)
	}

	seen := map[string]bool{}
	var lines []string
	lines = append(lines, fmt.Sprintf("WIKIDATA FACTS: %s", label))

	factFields := []struct {
		key  string
		name string
	}{
		{"employerLabel", "employer"},
		{"positionLabel", "position"},
		{"educationLabel", "education"},
		{"birthplaceLabel", "birthplace"},
		{"nationalityLabel", "nationality"},
		{"citizenshipLabel", "citizenship"},
		{"notableWorkLabel", "notable_work"},
	}

	for _, row := range bindings {
		for _, f := range factFields {
			if b, ok := row[f.key]; ok && b.Value != "" {
				entry := f.name + ": " + b.Value
				if !seen[entry] {
					seen[entry] = true
					lines = append(lines, entry)
				}
			}
		}
	}

	return strings.Join(lines, "\n")
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

	facts, err := fetchWikidataFacts(query)
	if err != nil {
		log.Printf("wikidata fetch error: %v", err)
		fmt.Fprintf(w, "data: [DONE]\n\n")
		flusher.Flush()
		return
	}

	payload := map[string]any{
		"text":        facts,
		"source_type": "wikidata",
		"source":      "wikidata",
		"query":       query,
	}
	payloadJSON, _ := json.Marshal(payload)
	block := contentBlock{Type: "text", Text: string(payloadJSON)}
	blockJSON, _ := json.Marshal(block)

	fmt.Fprintf(w, "data: %s\n\n", blockJSON)
	flusher.Flush()

	fmt.Fprintf(w, "data: [DONE]\n\n")
	flusher.Flush()
}

func handleHealth(w http.ResponseWriter, _ *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	fmt.Fprintf(w, `{"status":"ok","service":"mcp-wikidata"}`)
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
		port = "8092"
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

	log.Printf("mcp-wikidata plugin listening on :%s", port)
	if err := srv.ListenAndServe(); err != nil {
		log.Fatalf("server error: %v", err)
	}
}
