package models

import (
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// validEvent returns a RawEvent that passes Validate() for use as a base in
// tests. Callers mutate copies to exercise rejection paths.
func validEvent() *RawEvent {
	return &RawEvent{
		ID:            "evt-1",
		Source:        "http://plugin:8090",
		Timestamp:     time.Date(2026, 8, 11, 12, 0, 0, 0, time.UTC),
		Payload:       map[string]any{"k": "v"},
		PluginName:    "newsrss",
		PluginVersion: "1.0",
		SchemaVersion: SchemaVersion,
		TenantID:      "tenant-a",
		SourceName:    "PubMed Central",
		SourceURL:     "https://pubmed.ncbi.nlm.nih.gov/123",
	}
}

func TestValidate_AcceptsFullyPopulated(t *testing.T) {
	e := validEvent()
	assert.NoError(t, e.Validate())
}

func TestValidate_RejectsNil(t *testing.T) {
	var e *RawEvent
	err := e.Validate()
	require.Error(t, err)
	assert.Contains(t, err.Error(), "nil")
}

func TestValidate_RejectsMissingPluginName(t *testing.T) {
	e := validEvent()
	e.PluginName = ""
	err := e.Validate()
	require.Error(t, err)
	assert.Contains(t, err.Error(), "plugin_name")
}

func TestValidate_RejectsMissingSourceName(t *testing.T) {
	e := validEvent()
	e.SourceName = ""
	err := e.Validate()
	require.Error(t, err)
	assert.Contains(t, err.Error(), "source_name")
}

func TestValidate_RejectsZeroTimestamp(t *testing.T) {
	e := validEvent()
	e.Timestamp = time.Time{}
	err := e.Validate()
	require.Error(t, err)
	assert.Contains(t, err.Error(), "timestamp")
}

func TestValidate_RejectsMissingTenantID(t *testing.T) {
	e := validEvent()
	e.TenantID = ""
	err := e.Validate()
	require.Error(t, err)
	assert.Contains(t, err.Error(), "tenant_id")
}

func TestValidate_RejectsMissingSchemaVersion(t *testing.T) {
	e := validEvent()
	e.SchemaVersion = ""
	err := e.Validate()
	require.Error(t, err)
	assert.Contains(t, err.Error(), "schema_version")
}

func TestNewRawEvent_StampDefaults(t *testing.T) {
	e := NewRawEvent()
	assert.NotEmpty(t, e.ID)
	assert.False(t, e.Timestamp.IsZero())
	assert.Equal(t, SchemaVersion, e.SchemaVersion)
	// Timestamp should be UTC.
	assert.Equal(t, e.Timestamp.Location(), time.UTC)
}

func TestToKafkaEvent_RoundTripsAllFields(t *testing.T) {
	e := validEvent()
	k := e.ToKafkaEvent()
	require.NotNil(t, k)

	assert.Equal(t, e.ID, k.ID)
	assert.Equal(t, e.Source, k.Source)
	assert.Equal(t, e.Timestamp, k.Timestamp)
	assert.Equal(t, e.Payload, k.Payload)
	assert.Equal(t, e.PluginName, k.PluginName)
	assert.Equal(t, e.PluginVersion, k.PluginVersion)
	assert.Equal(t, e.IngestLatencyMs, k.IngestLatencyMs)
	assert.Equal(t, e.SchemaVersion, k.SchemaVersion)
	assert.Equal(t, e.TenantID, k.TenantID)
	assert.Equal(t, e.KIQID, k.KIQID)
	assert.Equal(t, e.SourceName, k.SourceName)
	assert.Equal(t, e.SourceURL, k.SourceURL)

	// Round-trip back.
	back := FromKafkaEvent(k)
	require.NotNil(t, back)
	assert.Equal(t, e.ID, back.ID)
	assert.Equal(t, e.SourceName, back.SourceName)
	assert.Equal(t, e.TenantID, back.TenantID)
}

func TestToKafkaEvent_NilReturnsNil(t *testing.T) {
	var e *RawEvent
	assert.Nil(t, e.ToKafkaEvent())
}

func TestFromKafkaEvent_NilReturnsNil(t *testing.T) {
	assert.Nil(t, FromKafkaEvent(nil))
}
