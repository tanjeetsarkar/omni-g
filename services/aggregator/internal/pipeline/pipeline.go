// Package pipeline wires the validation sidecar and Kafka producer into a
// single event-processing step.
package pipeline

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	"github.com/omni-g/aggregator/internal/ingest"
	kafkainternal "github.com/omni-g/aggregator/internal/kafka"
	"github.com/omni-g/aggregator/internal/metrics"
	"github.com/omni-g/aggregator/internal/validation"
	"github.com/omni-g/aggregator/pkg/models"
	"github.com/rs/zerolog/log"
)

// Publisher is the minimal interface required to publish a raw event.
// kafka.Producer satisfies this interface.
type Publisher interface {
	Publish(ctx context.Context, event *kafkainternal.RawEvent) error
}

// SchemaValidator validates an event payload against the schema sidecar.
// validation.Validator satisfies this interface.
type SchemaValidator interface {
	Validate(ctx context.Context, source string, payload map[string]any) (*validation.ValidationResult, error)
}

// Pipeline validates and publishes events from MCP plugin content blocks.
type Pipeline struct {
	validator SchemaValidator
	publisher Publisher
	topic     string
	tenantID  string
}

// New creates a Pipeline wired to the given validator and publisher.
// topic is used only for metrics labels. tenantID is stamped on every event.
func New(validator SchemaValidator, publisher Publisher, topic string, tenantID string) *Pipeline {
	return &Pipeline{
		validator: validator,
		publisher: publisher,
		topic:     topic,
		tenantID:  tenantID,
	}
}

// Process validates payload and publishes it as a RawEvent.
// source identifies the originating MCP plugin URL.
// pluginName and pluginVersion are stamped into the event envelope for provenance.
// kiqID is the optional Key Intelligence Question reference that tasked this
// collection; pass an empty string for untasked (general) collection.
// sourceName is the human-readable name of the originating source
// (e.g. "PubMed Central"); pass "" to default to pluginName.
// sourceURL is the canonical human-facing URL of the source document; pass ""
// when only the plugin URL is available.
// searchID is the optional search correlation ID that binds this event to a
// user-initiated /search or /enrich request; pass "" for autonomous collection.
//
// If the validation sidecar is unreachable the event is dropped and an error
// is returned (fail-closed). If the payload is invalid the event is counted as
// a validation failure and dropped without an error (the rejection is expected).
func (p *Pipeline) Process(ctx context.Context, source string, payload map[string]any, pluginName string, pluginVersion string, kiqID string, sourceName string, sourceURL string, searchID string) error {
	start := time.Now()
	logger := log.With().
		Str("source", source).
		Str("plugin_name", pluginName).
		Str("plugin_version", pluginVersion).
		Str("topic", p.topic).
		Str("tenant_id", p.tenantID).
		Str("kiq_id", kiqID).
		Str("source_name", sourceName).
		Str("source_url", sourceURL).
		Logger()

	logger.Info().Msg("pipeline processing started")

	// ── validate ──────────────────────────────────────────────────────────
	result, err := p.validator.Validate(ctx, source, payload)
	if err != nil {
		logger.Error().Err(err).Msg("validation sidecar unreachable")
		metrics.IngestTotal.WithLabelValues(source, "validation_error").Inc()
		return fmt.Errorf("validation sidecar: %w", err)
	}
	logger.Debug().Bool("valid", result.Valid).Int("error_count", len(result.Errors)).Msg("validation sidecar responded")

	if !result.Valid {
		reason := "schema_violation"
		if len(result.Errors) > 0 {
			reason = result.Errors[0].Field + ":" + result.Errors[0].Message
		}
		logger.Warn().Str("reason", reason).Msg("event failed schema validation, dropping")
		metrics.ValidationFailureTotal.WithLabelValues(source, reason).Inc()
		metrics.IngestTotal.WithLabelValues(source, "validation_failed").Inc()
		return nil // expected rejection — not an error from caller's perspective
	}

	// ── publish ───────────────────────────────────────────────────────────
	elapsed := time.Since(start).Milliseconds()
	// Default human-readable source name to the plugin name when the
	// upstream plugin did not supply a publisher/document title. Applied
	// here (before publish) so the value is observable regardless of which
	// Publisher implementation is wired in.
	effectiveSourceName := sourceName
	if effectiveSourceName == "" {
		effectiveSourceName = pluginName
	}

	// V4 Track 3: build the governance envelope (pkg/models.RawEvent) and
	// enforce the non-null provenance contract before publishing. This is the
	// second validation layer — the schema sidecar validates the payload
	// shape; Validate() validates the envelope provenance fields required by
	// the V4 roadmap (source_name, plugin_name, timestamp, tenant_id).
	evt := models.NewRawEvent()
	evt.Source = source
	evt.Payload = payload
	evt.PluginName = pluginName
	evt.PluginVersion = pluginVersion
	evt.IngestLatencyMs = elapsed
	evt.TenantID = p.tenantID
	evt.KIQID = kiqID
	evt.SourceName = effectiveSourceName
	evt.SourceURL = sourceURL
	evt.SearchID = searchID
	// NewRawEvent stamps ID/Timestamp/SchemaVersion; preserve them.

	if err := evt.Validate(); err != nil {
		logger.Warn().Err(err).Msg("envelope contract validation failed, dropping")
		metrics.IngestTotal.WithLabelValues(source, "envelope_invalid").Inc()
		return nil // envelope contract violation — drop, not a caller error
	}

	event := evt.ToKafkaEvent()

	if err := p.publisher.Publish(ctx, event); err != nil {
		logger.Error().Err(err).Msg("kafka publish failed")
		metrics.KafkaPublishTotal.WithLabelValues(p.topic, "error").Inc()
		metrics.IngestTotal.WithLabelValues(source, "publish_error").Inc()
		return fmt.Errorf("publish event: %w", err)
	}

	metrics.KafkaPublishTotal.WithLabelValues(p.topic, "ok").Inc()
	metrics.IngestTotal.WithLabelValues(source, "published").Inc()
	metrics.EventProcessingDuration.Observe(time.Since(start).Seconds())
	logger.Info().Str("event_id", event.ID).Int64("ingest_latency_ms", elapsed).Msg("pipeline processing completed")

	return nil
}

// SourceForTool returns a valid HTTP(S) URL suitable for the validation
// sidecar's `source` field. It prefers the tool descriptor's SourceURL; when
// that is empty it falls back to a synthetic but valid URL keyed on the tool
// name so the Processor's strict URL validator never rejects the event.
//
// The validation sidecar (Processor /validate) requires `source` to be a
// valid HTTP(S) URL — passing the tool *name* (e.g. "web_search") causes a
// 422 rejection and drops the event before it reaches Kafka.
func SourceForTool(toolName, toolSourceURL string) string {
	if toolSourceURL != "" {
		return toolSourceURL
	}
	return "https://omni-g.internal/tool/" + toolName
}

// ProcessBlock parses a ContentBlock's text as a JSON payload and forwards it
// to Process. Malformed JSON is dropped and logged.
// kiqID is the optional Key Intelligence Question reference that tasked this
// collection; pass an empty string for untasked (general) collection.
// sourceName and sourceURL carry human-readable provenance; pass "" to
// default sourceName to pluginName and leave sourceURL unset.
// searchID is the optional search correlation ID; pass "" for autonomous collection.
func (p *Pipeline) ProcessBlock(ctx context.Context, source string, text string, pluginName string, pluginVersion string, kiqID string, sourceName string, sourceURL string, searchID string) error {
	log.Info().Str("source", source).Str("plugin_name", pluginName).Str("kiq_id", kiqID).Str("source_name", sourceName).Msg("processing content block")

	var payload map[string]any
	if err := json.Unmarshal([]byte(text), &payload); err != nil {
		log.Warn().Str("source", source).Err(err).Msg("content block is not valid JSON, dropping")
		metrics.IngestTotal.WithLabelValues(source, "parse_error").Inc()
		return nil // non-fatal
	}

	// V4 Track 2: when the caller did not supply a human-readable source
	// name/URL, auto-extract them from the content-block payload (e.g.
	// document_title, publisher_name, source_url). This keeps provenance
	// non-empty for scheduled polls that have no caller-supplied metadata.
	if sourceName == "" || sourceURL == "" {
		prov := ingest.ExtractProvenance(text)
		if sourceName == "" {
			sourceName = prov.SourceName
		}
		if sourceURL == "" {
			sourceURL = prov.SourceURL
		}
	}

	return p.Process(ctx, source, payload, pluginName, pluginVersion, kiqID, sourceName, sourceURL, searchID)
}
