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

	err := p.Process(context.Background(), "http://plugin:8090", map[string]any{"source": "test", "payload": map[string]any{}}, "test-plugin", "1.0")

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

	err := p.Process(context.Background(), "http://plugin:8090", map[string]any{}, "test-plugin", "1.0")

	require.NoError(t, err) // rejection is not an error from caller's perspective
	assert.Empty(t, pub.published)
}

func TestProcess_ValidatorUnreachable_ReturnsError(t *testing.T) {
	v := &mockValidator{err: errors.New("connection refused")}
	pub := &mockPublisher{}
	p := pipeline.New(v, pub, "raw-feed", "test-tenant")

	err := p.Process(context.Background(), "http://plugin:8090", map[string]any{}, "test-plugin", "1.0")

	require.Error(t, err)
	assert.Contains(t, err.Error(), "validation sidecar")
	assert.Empty(t, pub.published)
}

func TestProcess_PublishFails_ReturnsError(t *testing.T) {
	v := &mockValidator{result: &validation.ValidationResult{Valid: true}}
	pub := &mockPublisher{err: errors.New("kafka broker unavailable")}
	p := pipeline.New(v, pub, "raw-feed", "test-tenant")

	err := p.Process(context.Background(), "http://plugin:8090", map[string]any{"source": "test", "payload": map[string]any{}}, "test-plugin", "1.0")

	require.Error(t, err)
	assert.Contains(t, err.Error(), "publish event")
}

// ─── ProcessBlock tests ───────────────────────────────────────────────────────

func TestProcessBlock_ValidJSON_Publishes(t *testing.T) {
	v := &mockValidator{result: &validation.ValidationResult{Valid: true}}
	pub := &mockPublisher{}
	p := pipeline.New(v, pub, "raw-feed", "test-tenant")

	err := p.ProcessBlock(context.Background(), "http://plugin:8090", `{"source":"shodan","payload":{"ip":"1.2.3.4"}}`, "test-plugin", "1.0")

	require.NoError(t, err)
	require.Len(t, pub.published, 1)
}

func TestProcessBlock_InvalidJSON_DropsWithoutError(t *testing.T) {
	v := &mockValidator{result: &validation.ValidationResult{Valid: true}}
	pub := &mockPublisher{}
	p := pipeline.New(v, pub, "raw-feed", "test-tenant")

	err := p.ProcessBlock(context.Background(), "http://plugin:8090", "not json {{", "test-plugin", "1.0")

	require.NoError(t, err) // malformed — not an error
	assert.Empty(t, pub.published)
}
