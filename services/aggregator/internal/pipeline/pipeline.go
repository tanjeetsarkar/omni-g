// Package pipeline wires the validation sidecar and Kafka producer into a
// single event-processing step.
package pipeline

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	"github.com/google/uuid"
	kafkainternal "github.com/omni-g/aggregator/internal/kafka"
	"github.com/omni-g/aggregator/internal/metrics"
	"github.com/omni-g/aggregator/internal/validation"
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
//
// If the validation sidecar is unreachable the event is dropped and an error
// is returned (fail-closed). If the payload is invalid the event is counted as
// a validation failure and dropped without an error (the rejection is expected).
func (p *Pipeline) Process(ctx context.Context, source string, payload map[string]any, pluginName string, pluginVersion string) error {
	start := time.Now()

	// ── validate ──────────────────────────────────────────────────────────
	result, err := p.validator.Validate(ctx, source, payload)
	if err != nil {
		log.Error().Str("source", source).Err(err).Msg("validation sidecar unreachable")
		metrics.IngestTotal.WithLabelValues(source, "validation_error").Inc()
		return fmt.Errorf("validation sidecar: %w", err)
	}

	if !result.Valid {
		reason := "schema_violation"
		if len(result.Errors) > 0 {
			reason = result.Errors[0].Field + ":" + result.Errors[0].Message
		}
		log.Warn().Str("source", source).Str("reason", reason).
			Msg("event failed schema validation, dropping")
		metrics.ValidationFailureTotal.WithLabelValues(source, reason).Inc()
		metrics.IngestTotal.WithLabelValues(source, "validation_failed").Inc()
		return nil // expected rejection — not an error from caller's perspective
	}

	// ── publish ───────────────────────────────────────────────────────────
	elapsed := time.Since(start).Milliseconds()
	event := &kafkainternal.RawEvent{
		ID:              uuid.New().String(),
		Source:          source,
		Timestamp:       time.Now().UTC(),
		Payload:         payload,
		PluginName:      pluginName,
		PluginVersion:   pluginVersion,
		IngestLatencyMs: elapsed,
		TenantID:        p.tenantID,
	}

	if err := p.publisher.Publish(ctx, event); err != nil {
		log.Error().Str("source", source).Err(err).Msg("kafka publish failed")
		metrics.KafkaPublishTotal.WithLabelValues(p.topic, "error").Inc()
		metrics.IngestTotal.WithLabelValues(source, "publish_error").Inc()
		return fmt.Errorf("publish event: %w", err)
	}

	metrics.KafkaPublishTotal.WithLabelValues(p.topic, "ok").Inc()
	metrics.IngestTotal.WithLabelValues(source, "published").Inc()
	metrics.EventProcessingDuration.Observe(time.Since(start).Seconds())

	return nil
}

// ProcessBlock parses a ContentBlock's text as a JSON payload and forwards it
// to Process. Malformed JSON is dropped and logged.
func (p *Pipeline) ProcessBlock(ctx context.Context, source string, text string, pluginName string, pluginVersion string) error {
	var payload map[string]any
	if err := json.Unmarshal([]byte(text), &payload); err != nil {
		log.Warn().Str("source", source).Str("text", text).
			Err(err).Msg("ContentBlock text is not valid JSON, dropping")
		metrics.IngestTotal.WithLabelValues(source, "parse_error").Inc()
		return nil // non-fatal
	}
	return p.Process(ctx, source, payload, pluginName, pluginVersion)
}
