package server

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"

	"github.com/google/uuid"
	"github.com/rs/zerolog/log"
)

// enrichEntityMeta describes the entity the caller wants to enrich.
type enrichEntityMeta struct {
	Name        string `json:"name"`
	Type        string `json:"type,omitempty"`
	Description string `json:"description,omitempty"`
}

// enrichRequest is the JSON body expected by POST /enrich.
type enrichRequest struct {
	Entity     enrichEntityMeta `json:"entity"`
	Plugins    []string         `json:"plugins"`     // optional; empty means all
	MaxResults int              `json:"max_results"` // hint per plugin; 0 = default
	TenantID   string           `json:"tenant_id"`
}

// enrichResponse is returned with HTTP 202 on success.
type enrichResponse struct {
	EnrichmentID   string              `json:"enrichment_id"`
	EventsQueued   int                 `json:"events_queued"`
	Status         string              `json:"status"`
	QueuedBySource []sourceResultCount `json:"queued_by_source"`
}

// HandleEnrich handles POST /enrich — targeted per-entity enrichment.
//
// Unlike POST /search (which accepts a free-form query), /enrich accepts
// structured entity metadata and builds a focused query string from it so
// the MCP plugins can return content specifically about that entity.
//
// The handler fans out only to the plugins named in the request (or all
// configured plugins when the list is empty) and publishes results to Kafka
// via the same pipeline used by /search.
func (h *SearchHandler) HandleEnrich(w http.ResponseWriter, r *http.Request) {
	var req enrichRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, `{"error":"invalid JSON body"}`, http.StatusBadRequest)
		return
	}
	if strings.TrimSpace(req.Entity.Name) == "" {
		http.Error(w, `{"error":"entity.name is required"}`, http.StatusBadRequest)
		return
	}

	enrichmentID := uuid.New().String()
	log.Info().
		Str("enrichment_id", enrichmentID).
		Str("entity_name", req.Entity.Name).
		Str("entity_type", req.Entity.Type).
		Msg("received /enrich request")

	// Build a focused query string from entity metadata.
	query := buildEnrichQuery(req.Entity)
	log.Debug().
		Str("enrichment_id", enrichmentID).
		Str("query", query).
		Msg("enrichment query constructed")

	// Resolve which plugins to use.
	plugins := req.Plugins
	if len(plugins) == 0 {
		for name := range h.pluginClients {
			plugins = append(plugins, name)
		}
	}

	type result struct {
		source string
		count  int
	}
	resultCh := make(chan result, len(plugins))
	bgCtx := context.Background()

	for _, pluginName := range plugins {
		client, ok := h.pluginClients[pluginName]
		if !ok {
			log.Warn().
				Str("enrichment_id", enrichmentID).
				Str("plugin", pluginName).
				Msg("/enrich: no client configured for plugin")
			resultCh <- result{source: pluginName, count: 0}
			continue
		}
		pluginURL, ok := h.pluginURLs[pluginName]
		if !ok || pluginURL == "" {
			log.Warn().
				Str("enrichment_id", enrichmentID).
				Str("plugin", pluginName).
				Msg("/enrich: no URL configured for plugin")
			resultCh <- result{source: pluginName, count: 0}
			continue
		}
		toolName, ok := h.pluginTools[pluginName]
		if !ok {
			log.Warn().
				Str("enrichment_id", enrichmentID).
				Str("plugin", pluginName).
				Msg("/enrich: no tool configured for plugin")
			resultCh <- result{source: pluginName, count: 0}
			continue
		}

		go func(name, url string) {
			log.Info().
				Str("enrichment_id", enrichmentID).
				Str("plugin", name).
				Str("tool", toolName).
				Msg("starting enrichment plugin call")
			count := h.callPlugin(bgCtx, enrichmentID, name, url, client, toolName, query)
			resultCh <- result{source: name, count: count}
		}(pluginName, pluginURL)
	}

	total := 0
	bySource := make([]sourceResultCount, 0, len(plugins))
	for range plugins {
		r := <-resultCh
		total += r.count
		bySource = append(bySource, sourceResultCount{Source: r.source, BlocksQueued: r.count})
	}

	writeJSON(w, http.StatusAccepted, enrichResponse{
		EnrichmentID:   enrichmentID,
		EventsQueued:   total,
		Status:         "queued",
		QueuedBySource: bySource,
	})
	log.Info().
		Str("enrichment_id", enrichmentID).
		Int("events_queued", total).
		Msg("/enrich request completed")
}

// buildEnrichQuery constructs a focused search query from entity metadata.
// The query is designed to retrieve factual, current information about the
// entity from external sources rather than relying on LLM background knowledge.
func buildEnrichQuery(entity enrichEntityMeta) string {
	parts := []string{entity.Name}
	if entity.Type != "" {
		parts = append(parts, entity.Type)
	}
	if entity.Description != "" {
		// Truncate description to avoid overly long queries.
		desc := entity.Description
		if len(desc) > 120 {
			desc = desc[:120]
		}
		parts = append(parts, desc)
	}
	return fmt.Sprintf("%s", strings.Join(parts, " "))
}
