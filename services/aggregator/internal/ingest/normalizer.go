// Package ingest normalises MCP tool-call content blocks into human-readable
// provenance metadata (source name / source URL) before the event enters the
// Kafka pipeline.
//
// MCP plugins return content blocks whose `text` field is a JSON payload. The
// payload shape varies by plugin, but commonly carries a document title,
// publisher name, or source URL alongside the main content. This package
// extracts those fields so the Processor and Delivery UI can render source
// tags without exposing raw plugin URLs or database IDs.
package ingest

import (
	"encoding/json"
	"strings"
)

// Provenance holds the human-readable source metadata extracted from a
// content-block payload. Zero values mean the field was not present.
type Provenance struct {
	SourceName string
	SourceURL  string
}

// candidateKeys lists JSON keys (case-insensitive) that are treated as a
// human-readable source name when present in a content-block payload.
var sourceNameKeys = []string{
	"document_title",
	"publisher_name",
	"publisher",
	"source_name",
	"title",
	"name",
	"headline",
}

// candidateURLKeys lists JSON keys that are treated as a canonical source URL.
var sourceURLKeys = []string{
	"source_url",
	"url",
	"link",
	"canonical_url",
	"permalink",
}

// ExtractProvenance parses a content-block text payload and returns the
// best-effort human-readable provenance. It never returns an error: malformed
// JSON or missing keys simply yield an empty Provenance, leaving the caller's
// existing defaults (e.g. SourceName = PluginName) in place.
//
// The lookup is shallow (top-level keys only) because MCP content blocks are
// flat JSON objects by convention; nested provenance is out of scope.
func ExtractProvenance(blockText string) Provenance {
	var payload map[string]any
	if err := json.Unmarshal([]byte(blockText), &payload); err != nil {
		return Provenance{}
	}
	return Provenance{
		SourceName: firstNonEmpty(payload, sourceNameKeys),
		SourceURL:  firstNonEmpty(payload, sourceURLKeys),
	}
}

// firstNonEmpty returns the first non-empty string value found under any of
// the candidate keys (case-insensitive). Returns "" when none match.
func firstNonEmpty(payload map[string]any, keys []string) string {
	// Build a lower-cased view of the payload for case-insensitive lookup.
	lowered := make(map[string]any, len(payload))
	for k, v := range payload {
		lowered[strings.ToLower(k)] = v
	}
	for _, key := range keys {
		if v, ok := lowered[key]; ok {
			if s, ok := v.(string); ok && strings.TrimSpace(s) != "" {
				return strings.TrimSpace(s)
			}
		}
	}
	return ""
}
