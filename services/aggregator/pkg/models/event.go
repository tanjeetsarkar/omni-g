package models

// Package models defines the canonical Aggregator event envelope and the
// governance contracts shared by the Tool Governance Harness and the
// Autonomous Ingestion Agents.
//
// The RawEvent type in this package is the governance-layer envelope: it
// carries the human-readable provenance fields (source_name, source_url,
// plugin_name, timestamp, tenant_id) that the V4 roadmap requires to be
// non-null on every event entering the pipeline. The Kafka transport envelope
// lives in internal/kafka; ToKafkaEvent() converts between the two at the
// publish boundary so the harness and agents depend only on pkg/models.

import (
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"
	kafkainternal "github.com/omni-g/aggregator/internal/kafka"
)

// SchemaVersion is the envelope schema version stamped on every event.
const SchemaVersion = "1.0"

// RawEvent is the canonical governance envelope for all events produced by
// the Aggregator. It mirrors internal/kafka.RawEvent but adds a Validate()
// method that enforces the V4 non-null provenance contract.
type RawEvent struct {
	ID              string         `json:"id"`
	Source          string         `json:"source"`
	Timestamp       time.Time      `json:"timestamp"`
	Payload         map[string]any `json:"payload"`
	PluginName      string         `json:"plugin_name,omitempty"`
	PluginVersion   string         `json:"plugin_version,omitempty"`
	IngestLatencyMs int64          `json:"ingest_latency_ms"`
	SchemaVersion   string         `json:"schema_version"`
	TenantID        string         `json:"tenant_id,omitempty"`
	// KIQID is the optional Key Intelligence Question reference that tasked
	// this collection. Empty string means the event is untasked (general
	// collection not bound to a specific KIQ).
	KIQID string `json:"kiq_id,omitempty"`
	// SourceName is the human-readable name of the originating source
	// (e.g. "PubMed Central", "ClinicalTrials.gov"). Required by V4 contract.
	SourceName string `json:"source_name,omitempty"`
	// SourceURL is the canonical human-facing URL of the source document.
	// Required by V4 contract when the source has a human-facing URL; may be
	// empty only for sources that genuinely have no URL (e.g. local feeds).
	SourceURL string `json:"source_url,omitempty"`
}

// NewRawEvent constructs a RawEvent with stamped defaults: a new UUID id, the
// current UTC timestamp, and the current schema version. The caller is still
// responsible for populating Source, Payload, PluginName, TenantID, and
// provenance before calling Validate().
func NewRawEvent() *RawEvent {
	return &RawEvent{
		ID:            uuid.New().String(),
		Timestamp:     time.Now().UTC(),
		SchemaVersion: SchemaVersion,
	}
}

// Validate enforces the V4 non-null provenance contract. It returns a
// descriptive error naming the first missing field, or nil when the event is
// safe to publish.
//
// Required fields:
//   - SourceName  — human-readable source name (V4 Track 3 Module 3.1)
//   - PluginName  — originating plugin identity
//   - Timestamp   — must not be zero
//   - TenantID    — multi-tenant isolation (Principle 6)
//
// SourceURL is strongly recommended but not hard-required because some sources
// (e.g. local RSS feeds) genuinely have no human-facing URL; callers should
// still populate it whenever possible.
func (e *RawEvent) Validate() error {
	if e == nil {
		return errors.New("raw event is nil")
	}
	if e.PluginName == "" {
		return errors.New("plugin_name is required")
	}
	if e.SourceName == "" {
		return errors.New("source_name is required")
	}
	if e.Timestamp.IsZero() {
		return errors.New("timestamp is required")
	}
	if e.TenantID == "" {
		return errors.New("tenant_id is required (multi-tenant isolation)")
	}
	if e.SchemaVersion == "" {
		return fmt.Errorf("schema_version is required")
	}
	return nil
}

// ToKafkaEvent converts the governance envelope into the Kafka transport
// envelope. This is the single conversion point at the publish boundary so
// the harness and agents never depend on internal/kafka directly.
func (e *RawEvent) ToKafkaEvent() *kafkainternal.RawEvent {
	if e == nil {
		return nil
	}
	return &kafkainternal.RawEvent{
		ID:              e.ID,
		Source:          e.Source,
		Timestamp:       e.Timestamp,
		Payload:         e.Payload,
		PluginName:      e.PluginName,
		PluginVersion:   e.PluginVersion,
		IngestLatencyMs: e.IngestLatencyMs,
		SchemaVersion:   e.SchemaVersion,
		TenantID:        e.TenantID,
		KIQID:           e.KIQID,
		SourceName:      e.SourceName,
		SourceURL:       e.SourceURL,
	}
}

// FromKafkaEvent converts a Kafka transport envelope back into the governance
// envelope. Used by tests and by any consumer that needs to re-validate an
// event that already traversed the transport layer.
func FromKafkaEvent(k *kafkainternal.RawEvent) *RawEvent {
	if k == nil {
		return nil
	}
	return &RawEvent{
		ID:              k.ID,
		Source:          k.Source,
		Timestamp:       k.Timestamp,
		Payload:         k.Payload,
		PluginName:      k.PluginName,
		PluginVersion:   k.PluginVersion,
		IngestLatencyMs: k.IngestLatencyMs,
		SchemaVersion:   k.SchemaVersion,
		TenantID:        k.TenantID,
		KIQID:           k.KIQID,
		SourceName:      k.SourceName,
		SourceURL:       k.SourceURL,
	}
}
