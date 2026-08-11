package server

import (
	"context"
	"encoding/json"
	"net/http"

	"github.com/google/uuid"
	"github.com/omni-g/aggregator/internal/mcp"
	"github.com/omni-g/aggregator/internal/pipeline"
	"github.com/omni-g/aggregator/pkg/harness"
	"github.com/rs/zerolog/log"
)

// sourceTool maps a logical source name (as used in /search and /enrich
// request bodies) to the governed harness tool name that backs it.
type sourceTool struct {
	toolName string
}

// SearchHandler handles POST /search and POST /enrich — on-demand search and
// enrichment across the governed domain-service tools. All tool calls route
// through the 9-stage Tool Governance Harness so on-demand queries are subject
// to the same validation, permission, circuit-breaker, and observability
// guarantees as autonomous agent ingestion.
type SearchHandler struct {
	// sourceTools maps logical source name → governed tool name.
	sourceTools map[string]string
	// defaultSources is the order of sources used when a request omits the
	// sources/plugins list.
	defaultSources []string
	harness        *harness.Harness
	pipeline       *pipeline.Pipeline
	tenantID       string
}

// NewSearchHandler constructs a SearchHandler backed by the harness.
// sourceTools maps logical source name (e.g. "wikipedia", "newsrss") →
// governed harness tool name (e.g. "web_search", "search_news").
func NewSearchHandler(
	sourceTools map[string]string,
	pl *pipeline.Pipeline,
	h *harness.Harness,
	tenantID string,
) *SearchHandler {
	defaults := make([]string, 0, len(sourceTools))
	for name := range sourceTools {
		defaults = append(defaults, name)
	}
	return &SearchHandler{
		sourceTools:    sourceTools,
		defaultSources: defaults,
		harness:        h,
		pipeline:       pl,
		tenantID:       tenantID,
	}
}

// searchRequest is the JSON body expected by POST /search.
type searchRequest struct {
	Query   string   `json:"query"`
	Sources []string `json:"sources"`
}

type sourceResultCount struct {
	Source       string `json:"source"`
	BlocksQueued int    `json:"blocks_queued"`
}

// searchResponse is returned with HTTP 202.
type searchResponse struct {
	SearchID       string              `json:"search_id"`
	EventsQueued   int                 `json:"events_queued"`
	QueuedBySource []sourceResultCount `json:"queued_by_source"`
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
	log.Info().Str("search_id", searchID).Str("query", req.Query).Msg("/search request received")

	sources := h.resolveSources(req.Sources)
	perm := harness.Permission{TenantID: h.tenantID} // allow-all for on-demand queries

	total, bySource := h.fanOutThroughHarness(r.Context(), searchID, sources, req.Query, perm, "")

	writeJSON(w, http.StatusAccepted, searchResponse{
		SearchID:       searchID,
		EventsQueued:   total,
		QueuedBySource: bySource,
	})
	log.Info().Str("search_id", searchID).Int("events_queued", total).Msg("/search request completed")
}

// resolveSources returns the source list to use, defaulting to all configured
// sources when the request omits it.
func (h *SearchHandler) resolveSources(requested []string) []string {
	if len(requested) > 0 {
		return requested
	}
	return h.defaultSources
}

// fanOutThroughHarness invokes the governed tool for each source in parallel
// and forwards the resulting blocks to the pipeline. Returns the total block
// count and per-source counts. kiqID is optional (empty for untasked).
func (h *SearchHandler) fanOutThroughHarness(
	parentCtx context.Context,
	correlationID string,
	sources []string,
	query string,
	perm harness.Permission,
	kiqID string,
) (int, []sourceResultCount) {
	type result struct {
		source string
		count  int
	}
	resultCh := make(chan result, len(sources))
	bgCtx := context.Background()

	for _, source := range sources {
		toolName, ok := h.sourceTools[source]
		if !ok {
			log.Warn().Str("source", source).Str("correlation_id", correlationID).
				Msg("no governed tool configured for source")
			resultCh <- result{source: source, count: 0}
			continue
		}

		go func(src, tool string) {
			count := h.invokeGovernedTool(bgCtx, correlationID, src, tool, query, perm, kiqID)
			resultCh <- result{source: src, count: count}
		}(source, toolName)
	}

	total := 0
	bySource := make([]sourceResultCount, 0, len(sources))
	for range sources {
		r := <-resultCh
		total += r.count
		bySource = append(bySource, sourceResultCount{Source: r.source, BlocksQueued: r.count})
	}
	return total, bySource
}

// invokeGovernedTool calls a single governed tool through the 9-stage harness
// and forwards each resulting block into the pipeline. Returns the number of
// blocks successfully queued.
func (h *SearchHandler) invokeGovernedTool(
	ctx context.Context,
	correlationID string,
	sourceName string,
	toolName string,
	query string,
	perm harness.Permission,
	kiqID string,
) int {
	logger := log.With().Str("correlation_id", correlationID).Str("source", sourceName).Str("tool", toolName).Logger()

	args := map[string]any{}
	if query != "" {
		args["query"] = query
	}

	result, err := h.harness.InvokeTool(ctx, toolName, args, perm, kiqID, h.tenantID)
	if err != nil {
		logger.Warn().Err(err).Msg("governed tool invocation failed")
		return 0
	}

	count := 0
	for _, block := range result.Blocks {
		if block.Type != mcp.ContentTypeText || block.Text == "" {
			continue
		}
		if err := h.pipeline.ProcessBlock(ctx, pipeline.SourceForTool(result.Tool.Name, result.Tool.SourceURL), block.Text,
			result.Tool.Name, result.Tool.Version, kiqID, result.Tool.SourceName, result.Tool.SourceURL); err != nil {
			logger.Warn().Err(err).Msg("pipeline.ProcessBlock error")
			continue
		}
		count++
	}
	logger.Debug().Int("blocks_queued", count).Msg("governed source completed")
	return count
}
