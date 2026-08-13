package server

import (
	"context"
	"encoding/json"
	"net/http"

	"github.com/google/uuid"
	"github.com/omni-g/aggregator/internal/mcp"
	"github.com/omni-g/aggregator/internal/pipeline"
	"github.com/omni-g/aggregator/pkg/agent"
	"github.com/omni-g/aggregator/pkg/harness"
	"github.com/rs/zerolog/log"
)

// SearchHandler handles POST /search and POST /enrich — on-demand search and
// enrichment across mu-discovered tools. All tool calls route through the
// 9-stage Tool Governance Harness so on-demand queries are subject to the
// same validation, permission, circuit-breaker, and observability guarantees
// as autonomous agent ingestion.
//
// V6: The AgenticRouter is the sole tool selection mechanism. The legacy
// hardcoded source→tool fan-out has been removed. Mu provides all tools
// (web_search, news_search, weather_forecast, markets_list, etc.).
type SearchHandler struct {
	harness  *harness.Harness
	pipeline *pipeline.Pipeline
	tenantID string
	// router is the AgenticRouter for intelligent tool selection.
	// Must be set via SetRouter() before the server starts.
	router *agent.AgenticRouter
}

// NewSearchHandler constructs a SearchHandler backed by the harness.
// The router must be injected via SetRouter() before use.
func NewSearchHandler(
	pl *pipeline.Pipeline,
	h *harness.Harness,
	tenantID string,
) *SearchHandler {
	return &SearchHandler{
		harness:  h,
		pipeline: pl,
		tenantID: tenantID,
	}
}

// SetRouter injects the AgenticRouter for intelligent tool selection.
// Must be called before the server starts accepting requests.
func (h *SearchHandler) SetRouter(r *agent.AgenticRouter) {
	h.router = r
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

	// V6: Always use AgenticRouter for intelligent tool selection.
	// If no router is set, return an error — the router is mandatory.
	if h.router == nil {
		log.Error().Str("search_id", searchID).Msg("no router configured for /search")
		http.Error(w, `{"error":"search router not configured"}`, http.StatusInternalServerError)
		return
	}

	total, bySource := h.routeThroughRouter(r.Context(), searchID, req.Query)

	writeJSON(w, http.StatusAccepted, searchResponse{
		SearchID:       searchID,
		EventsQueued:   total,
		QueuedBySource: bySource,
	})
	log.Info().Str("search_id", searchID).Int("events_queued", total).Msg("/search request completed")
}

// routeThroughRouter uses the AgenticRouter to intelligently select and invoke
// tools for the query. Returns total blocks queued and per-tool counts.
func (h *SearchHandler) routeThroughRouter(
	ctx context.Context,
	searchID string,
	query string,
) (int, []sourceResultCount) {
	logger := log.With().Str("search_id", searchID).Str("query", query).Logger()
	logger.Info().Msg("routing /search through AgenticRouter")

	result, err := h.router.Route(ctx, query, "", searchID)
	if err != nil {
		logger.Error().Err(err).Msg("router.Route failed")
		return 0, nil
	}

	total := 0
	bySource := make([]sourceResultCount, 0, len(result.Results))

	for _, invokeResult := range result.Results {
		count := 0
		for _, block := range invokeResult.Blocks {
			if block.Type != mcp.ContentTypeText || block.Text == "" {
				continue
			}
			if err := h.pipeline.ProcessBlock(ctx,
				pipeline.SourceForTool(invokeResult.Tool.Name, invokeResult.Tool.SourceURL),
				block.Text,
				invokeResult.Tool.Name,
				invokeResult.Tool.Version,
				"",
				invokeResult.Tool.SourceName,
				invokeResult.Tool.SourceURL,
				searchID,
			); err != nil {
				logger.Warn().Str("tool", invokeResult.Tool.Name).Err(err).Msg("pipeline.ProcessBlock error")
				continue
			}
			count++
		}
		total += count
		bySource = append(bySource, sourceResultCount{
			Source:       invokeResult.Tool.Name,
			BlocksQueued: count,
		})
	}

	// Log router errors.
	for _, e := range result.Errors {
		logger.Warn().Err(e).Msg("router tool error")
	}

	logger.Info().
		Int("total_blocks", total).
		Strs("selected_tools", result.SelectedTools).
		Msg("router /search completed")

	return total, bySource
}
