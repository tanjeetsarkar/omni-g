package pipeline_test

import (
	"context"
	"errors"
	"testing"

	kafkainternal "github.com/omni-g/aggregator/internal/kafka"
	"github.com/omni-g/aggregator/internal/pipeline"
	"github.com/omni-g/aggregator/internal/validation"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// ─── mocks ───────────────────────────────────────────────────────────────────

type mockValidator struct {
	result *validation.ValidationResult
	err    error
}

func (m *mockValidator) Validate(_ context.Context, _ string, _ map[string]any) (*validation.ValidationResult, error) {
	return m.result, m.err
}

type mockPublisher struct {
	published []*kafkainternal.RawEvent
	err       error
}

func (m *mockPublisher) Publish(_ context.Context, e *kafkainternal.RawEvent) error {
	if m.err != nil {
		return m.err
	}
	m.published = append(m.published, e)
	return nil
}

// ─── Process tests ────────────────────────────────────────────────────────────

func TestProcess_ValidPayload_Publishes(t *testing.T) {
	v := &mockValidator{result: &validation.ValidationResult{Valid: true}}
	pub := &mockPublisher{}
	p := pipeline.New(v, pub, "raw-feed", "test-tenant")

	err := p.Process(context.Background(), "http://plugin:8090", map[string]any{"source": "test", "payload": map[string]any{}}, "test-plugin", "1.0", "", "", "", "")

	require.NoError(t, err)
	require.Len(t, pub.published, 1)
	assert.Equal(t, "http://plugin:8090", pub.published[0].Source)
	assert.NotEmpty(t, pub.published[0].ID)
}

func TestProcess_InvalidPayload_DropsWithoutError(t *testing.T) {
	v := &mockValidator{result: &validation.ValidationResult{
		Valid:  false,
		Errors: []validation.ErrorDetail{{Field: "source", Message: "field 'source' is required"}},
	}}
	pub := &mockPublisher{}
	p := pipeline.New(v, pub, "raw-feed", "test-tenant")

	err := p.Process(context.Background(), "http://plugin:8090", map[string]any{}, "test-plugin", "1.0", "", "", "", "")

	require.NoError(t, err) // rejection is not an error from caller's perspective
	assert.Empty(t, pub.published)
}

func TestProcess_ValidatorUnreachable_ReturnsError(t *testing.T) {
	v := &mockValidator{err: errors.New("connection refused")}
	pub := &mockPublisher{}
	p := pipeline.New(v, pub, "raw-feed", "test-tenant")

	err := p.Process(context.Background(), "http://plugin:8090", map[string]any{}, "test-plugin", "1.0", "", "", "", "")

	require.Error(t, err)
	assert.Contains(t, err.Error(), "validation sidecar")
	assert.Empty(t, pub.published)
}

func TestProcess_PublishFails_ReturnsError(t *testing.T) {
	v := &mockValidator{result: &validation.ValidationResult{Valid: true}}
	pub := &mockPublisher{err: errors.New("kafka broker unavailable")}
	p := pipeline.New(v, pub, "raw-feed", "test-tenant")

	err := p.Process(context.Background(), "http://plugin:8090", map[string]any{"source": "test", "payload": map[string]any{}}, "test-plugin", "1.0", "", "", "", "")

	require.Error(t, err)
	assert.Contains(t, err.Error(), "publish event")
}

// ─── ProcessBlock tests ───────────────────────────────────────────────────────

func TestProcessBlock_ValidJSON_Publishes(t *testing.T) {
	v := &mockValidator{result: &validation.ValidationResult{Valid: true}}
	pub := &mockPublisher{}
	p := pipeline.New(v, pub, "raw-feed", "test-tenant")

	err := p.ProcessBlock(context.Background(), "http://plugin:8090", `{"source":"shodan","payload":{"ip":"1.2.3.4"}}`, "test-plugin", "1.0", "", "", "", "")

	require.NoError(t, err)
	require.Len(t, pub.published, 1)
}

func TestProcessBlock_InvalidJSON_DropsWithoutError(t *testing.T) {
	v := &mockValidator{result: &validation.ValidationResult{Valid: true}}
	pub := &mockPublisher{}
	p := pipeline.New(v, pub, "raw-feed", "test-tenant")

	err := p.ProcessBlock(context.Background(), "http://plugin:8090", "not json {{", "test-plugin", "1.0", "", "", "", "")

	require.NoError(t, err) // malformed — not an error
	assert.Empty(t, pub.published)
}

func TestProcess_WithKIQID_StampsEventEnvelope(t *testing.T) {
	v := &mockValidator{result: &validation.ValidationResult{Valid: true}}
	pub := &mockPublisher{}
	p := pipeline.New(v, pub, "raw-feed", "test-tenant")

	err := p.Process(context.Background(), "http://plugin:8090", map[string]any{"text": "breaking news"}, "test-plugin", "1.0", "kiq--abc123", "", "", "")

	require.NoError(t, err)
	require.Len(t, pub.published, 1)
	assert.Equal(t, "kiq--abc123", pub.published[0].KIQID)
}

func TestProcess_UntaskedEvent_HasEmptyKIQID(t *testing.T) {
	v := &mockValidator{result: &validation.ValidationResult{Valid: true}}
	pub := &mockPublisher{}
	p := pipeline.New(v, pub, "raw-feed", "test-tenant")

	err := p.Process(context.Background(), "http://plugin:8090", map[string]any{"text": "general feed"}, "test-plugin", "1.0", "", "", "", "")

	require.NoError(t, err)
	require.Len(t, pub.published, 1)
	assert.Equal(t, "", pub.published[0].KIQID, "untasked events must have an empty kiq_id")
}

// ─── Provenance tests (V4 Track 2) ───────────────────────────────────────────

func TestProcess_PropagatesSourceNameAndURL(t *testing.T) {
	v := &mockValidator{result: &validation.ValidationResult{Valid: true}}
	pub := &mockPublisher{}
	p := pipeline.New(v, pub, "raw-feed", "test-tenant")

	err := p.Process(context.Background(), "http://plugin:8090", map[string]any{"text": "breaking news"}, "pubmed-scraper", "1.0", "", "PubMed Central", "https://pubmed.ncbi.nlm.nih.gov/12345", "")

	require.NoError(t, err)
	require.Len(t, pub.published, 1)
	assert.Equal(t, "PubMed Central", pub.published[0].SourceName)
	assert.Equal(t, "https://pubmed.ncbi.nlm.nih.gov/12345", pub.published[0].SourceURL)
}

func TestProcess_DefaultsSourceNameToPluginName(t *testing.T) {
	v := &mockValidator{result: &validation.ValidationResult{Valid: true}}
	pub := &mockPublisher{}
	p := pipeline.New(v, pub, "raw-feed", "test-tenant")

	err := p.Process(context.Background(), "http://plugin:8090", map[string]any{"text": "breaking news"}, "mcp-health-scraper", "1.0", "", "", "", "")

	require.NoError(t, err)
	require.Len(t, pub.published, 1)
	// Producer.Publish defaults empty SourceName to PluginName.
	assert.Equal(t, "mcp-health-scraper", pub.published[0].SourceName)
	assert.Equal(t, "", pub.published[0].SourceURL)
}

// ─── ProcessBlock provenance auto-extraction tests (V4 Track 2) ──────────────

func TestProcessBlock_AutoExtractsProvenanceFromContentBlock(t *testing.T) {
	v := &mockValidator{result: &validation.ValidationResult{Valid: true}}
	pub := &mockPublisher{}
	p := pipeline.New(v, pub, "raw-feed", "test-tenant")

	// Content block carries document_title + source_url but caller passes
	// empty sourceName/sourceURL (scheduled poll path).
	block := `{"document_title":"PubMed Central Article","source_url":"https://pubmed.ncbi.nlm.nih.gov/12345","text":"article body"}`
	err := p.ProcessBlock(context.Background(), "http://plugin:8090", block, "pubmed-scraper", "1.0", "", "", "", "")

	require.NoError(t, err)
	require.Len(t, pub.published, 1)
	assert.Equal(t, "PubMed Central Article", pub.published[0].SourceName)
	assert.Equal(t, "https://pubmed.ncbi.nlm.nih.gov/12345", pub.published[0].SourceURL)
}

func TestProcessBlock_CallerSourceNameOverridesAutoExtraction(t *testing.T) {
	v := &mockValidator{result: &validation.ValidationResult{Valid: true}}
	pub := &mockPublisher{}
	p := pipeline.New(v, pub, "raw-feed", "test-tenant")

	// Caller supplies an explicit sourceName; auto-extraction must not override it.
	block := `{"document_title":"Auto Title","text":"body"}`
	err := p.ProcessBlock(context.Background(), "http://plugin:8090", block, "plugin-x", "1.0", "", "Explicit Name", "", "")

	require.NoError(t, err)
	require.Len(t, pub.published, 1)
	assert.Equal(t, "Explicit Name", pub.published[0].SourceName)
}
