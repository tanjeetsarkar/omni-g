package server

import (
	"encoding/json"
	"fmt"
	"net/http"
	"strings"

	"github.com/google/uuid"
	"github.com/omni-g/aggregator/pkg/harness"
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
// the governed tools can return content specifically about that entity.
//
// The handler fans out only to the sources named in the request (or all
// configured sources when the list is empty) and publishes results to Kafka
// via the same harness-backed path used by /search. All tool calls route
// through the 9-stage Tool Governance Harness.
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

	// Resolve which sources to use (defaults to all configured sources).
	sources := h.resolveSources(req.Plugins)
	perm := harness.Permission{TenantID: h.tenantID} // allow-all for on-demand

	total, bySource := h.fanOutThroughHarness(r.Context(), enrichmentID, sources, query, perm, "")

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
