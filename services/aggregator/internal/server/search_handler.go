package server

import (
	"context"
	"encoding/json"
	"net/http"

	"github.com/google/uuid"
	"github.com/omni-g/aggregator/internal/mcp"
	"github.com/omni-g/aggregator/internal/pipeline"
	"github.com/rs/zerolog/log"
)

// sourcePluginConfig maps logical source names to their plugin URL env key and
// the tool name to invoke.
type sourcePluginConfig struct {
	url      string
	toolName string
}

// SearchHandler handles POST /search — on-demand search across OSINT plugins.
type SearchHandler struct {
	// pluginClients maps logical source name → MCP client.
	pluginClients map[string]*mcp.Client
	// pluginURLs maps logical source name → plugin base URL.
	pluginURLs map[string]string
	// pluginTools maps logical source name → tool name to call.
	pluginTools map[string]string
	pipeline    *pipeline.Pipeline
}

// NewSearchHandler constructs a SearchHandler.
// pluginURLs maps logical source name (e.g. "wikipedia") → base URL.
// pluginTools maps logical source name → tool name to invoke.
func NewSearchHandler(
	pluginURLs map[string]string,
	pluginTools map[string]string,
	pl *pipeline.Pipeline,
) *SearchHandler {
	clients := make(map[string]*mcp.Client, len(pluginURLs))
	urls := make(map[string]string, len(pluginURLs))
	for name, u := range pluginURLs {
		if u != "" {
			clients[name] = mcp.NewClient(u)
			urls[name] = u
		}
	}
	return &SearchHandler{
		pluginClients: clients,
		pluginURLs:    urls,
		pluginTools:   pluginTools,
		pipeline:      pl,
	}
}

// searchRequest is the JSON body expected by POST /search.
type searchRequest struct {
	Query   string   `json:"query"`
	Sources []string `json:"sources"`
}

// searchResponse is returned with HTTP 202.
type searchResponse struct {
	SearchID     string `json:"search_id"`
	EventsQueued int    `json:"events_queued"`
}

// ServeHTTP handles POST /search.
func (h *SearchHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	var req searchRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, `{"error":"invalid JSON body"}`, http.StatusBadRequest)
		return
	}
	if req.Query == "" {
		http.Error(w, `{"error":"query is required"}`, http.StatusBadRequest)
		return
	}

	searchID := uuid.New().String()

	// If no sources specified, use all configured plugins.
	sources := req.Sources
	if len(sources) == 0 {
		for name := range h.pluginClients {
			sources = append(sources, name)
		}
	}

	// Fan out to each requested plugin in background goroutines.
	// We count events queued synchronously via a channel so we can return
	// the total in the 202 response without blocking.
	type result struct{ count int }
	resultCh := make(chan result, len(sources))

	bgCtx := context.Background()

	for _, source := range sources {
		client, ok := h.pluginClients[source]
		if !ok {
			log.Warn().Str("source", source).Msg("/search: no plugin configured for source")
			resultCh <- result{0}
			continue
		}
		pluginURL, ok := h.pluginURLs[source]
		if !ok || pluginURL == "" {
			log.Warn().Str("source", source).Msg("/search: no plugin URL configured for source")
			resultCh <- result{0}
			continue
		}
		toolName, ok := h.pluginTools[source]
		if !ok {
			log.Warn().Str("source", source).Msg("/search: no tool configured for source")
			resultCh <- result{0}
			continue
		}

		go func(src string, srcURL string, c *mcp.Client, tool string) {
			count := h.callPlugin(bgCtx, searchID, src, srcURL, c, tool, req.Query)
			resultCh <- result{count}
		}(source, pluginURL, client, toolName)
	}

	// Collect counts — wait for all goroutines.
	total := 0
	for range sources {
		r := <-resultCh
		total += r.count
	}

	writeJSON(w, http.StatusAccepted, searchResponse{
		SearchID:     searchID,
		EventsQueued: total,
	})
}

// callPlugin calls a single tool and forwards each content block into the
// pipeline. Returns the number of blocks successfully queued.
func (h *SearchHandler) callPlugin(
	ctx context.Context,
	searchID string,
	sourceName string,
	sourceURL string,
	client *mcp.Client,
	toolName string,
	query string,
) int {
	logger := log.With().Str("search_id", searchID).Str("source", sourceName).Logger()

	ch, err := client.CallTool(ctx, toolName, map[string]any{"query": query})
	if err != nil {
		logger.Error().Err(err).Msg("tool call failed")
		return 0
	}

	count := 0
	for block := range ch {
		if block.Type != mcp.ContentTypeText || block.Text == "" {
			continue
		}
		if err := h.pipeline.ProcessBlock(ctx, sourceURL, block.Text, toolName, ""); err != nil {
			logger.Warn().Err(err).Msg("pipeline.ProcessBlock error")
			continue
		}
		count++
	}

	logger.Info().Int("blocks_queued", count).Msg("search source completed")
	return count
}
