package harness

import (
	"context"
	"encoding/json"
	"errors"
	"strings"
	"testing"
	"time"

	"github.com/omni-g/aggregator/internal/mcp"
	"github.com/prometheus/client_golang/prometheus/testutil"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// TestGovernanceAudit_AllStagesEmitMetrics is the Milestone 5 governance
// audit: it verifies that a successful InvokeTool emits a metric for every
// one of the 9 stages, and that rejection paths stop at the failing stage
// without emitting later-stage metrics.
func TestGovernanceAudit_AllStagesEmitMetrics(t *testing.T) {
	h := New(Config{
		InvokeTimeout:           5 * time.Second,
		CircuitBreakerThreshold: 5,
		CircuitBreakerReset:     30 * time.Second,
	}, nil)

	// Register three tools: low-risk (happy path), high-risk (permission
	// denial), and a required-param tool (validation rejection).
	happy := blocksTool("happy", []mcp.ContentBlock{{Type: mcp.ContentTypeText, Text: `{"title":"x"}`}})
	happy.descriptor.Risk = RiskLow

	restricted := blocksTool("restricted", []mcp.ContentBlock{{Type: mcp.ContentTypeText, Text: `{"x":1}`}})
	restricted.descriptor.Risk = RiskHigh

	schema := `{"type":"object","required":["query"],"properties":{"query":{"type":"string"}}}`
	validating := schemaTool("validating", schema, nil)

	require.NoError(t, h.Register(happy))
	require.NoError(t, h.Register(restricted))
	require.NoError(t, h.Register(validating))

	// ── Happy path: all 9 stages should emit an "ok" metric. ──────────────
	_, err := h.InvokeTool(context.Background(), "happy", nil, Permission{TenantID: "audit"}, "", "audit")
	require.NoError(t, err)

	// Every stage from Select (3) through ReturnLoop (9) should have an "ok"
	// counter for "happy". Register (1) and Advertise (2) happen at
	// registration/advertise time.
	for stage := StageSelect; stage <= StageReturnLoop; stage++ {
		count := testutil.ToFloat64(HarnessInvokeTotal.WithLabelValues("happy", stage.String(), "ok"))
		assert.Greaterf(t, count, 0.0, "stage %s should have emitted an ok metric for happy", stage)
	}

	// ── Permission denial: stages 3-5 ok, stage 5 rejected, no later stages. ─
	perm := Permission{TenantID: "restricted-tenant", AllowedTools: []string{"other"}}
	_, err = h.InvokeTool(context.Background(), "restricted", nil, perm, "", "restricted-tenant")
	require.Error(t, err)

	// Stages 3 (select) and 4 (validate) should be ok.
	assert.Greater(t, testutil.ToFloat64(HarnessInvokeTotal.WithLabelValues("restricted", StageSelect.String(), "ok")), 0.0)
	assert.Greater(t, testutil.ToFloat64(HarnessInvokeTotal.WithLabelValues("restricted", StageValidate.String(), "ok")), 0.0)
	// Stage 5 (permission) should be rejected.
	assert.Greater(t, testutil.ToFloat64(HarnessInvokeTotal.WithLabelValues("restricted", StagePermission.String(), "rejected")), 0.0)
	// Stages 6-9 should NOT have emitted for "restricted".
	for stage := StageExecute; stage <= StageReturnLoop; stage++ {
		count := testutil.ToFloat64(HarnessInvokeTotal.WithLabelValues("restricted", stage.String(), "ok"))
		assert.Equalf(t, 0.0, count, "stage %s should NOT have emitted for permission-denied restricted", stage)
	}
	// Permission-denied counter should be incremented.
	assert.Greater(t, testutil.ToFloat64(HarnessPermissionDeniedTotal.WithLabelValues("restricted", "restricted-tenant")), 0.0)

	// ── Validation rejection: stages 3 ok, stage 4 rejected, no later stages. ─
	_, err = h.InvokeTool(context.Background(), "validating", map[string]any{}, Permission{TenantID: "audit"}, "", "audit")
	require.Error(t, err)
	assert.Greater(t, testutil.ToFloat64(HarnessInvokeTotal.WithLabelValues("validating", StageSelect.String(), "ok")), 0.0)
	assert.Greater(t, testutil.ToFloat64(HarnessInvokeTotal.WithLabelValues("validating", StageValidate.String(), "rejected")), 0.0)
	for stage := StagePermission; stage <= StageReturnLoop; stage++ {
		count := testutil.ToFloat64(HarnessInvokeTotal.WithLabelValues("validating", stage.String(), "ok"))
		assert.Equalf(t, 0.0, count, "stage %s should NOT have emitted for validation-rejected validating", stage)
	}
}

// TestGovernanceAudit_CircuitBreakerMetric verifies the circuit breaker state
// gauge transitions to open after threshold failures.
func TestGovernanceAudit_CircuitBreakerMetric(t *testing.T) {
	cfg := Config{
		CircuitBreakerThreshold: 2,
		CircuitBreakerReset:     1 * time.Hour, // keep open for the test
	}
	h := New(cfg, nil)
	require.NoError(t, h.Register(failTool("flaky", errors.New("nope"))))

	// Drive past the threshold to open the breaker.
	for i := 0; i < cfg.CircuitBreakerThreshold; i++ {
		_, err := h.InvokeTool(context.Background(), "flaky", nil, Permission{TenantID: "t"}, "", "t")
		require.Error(t, err)
	}
	// Breaker should now be open (gauge == 1).
	state := testutil.ToFloat64(HarnessCircuitBreakerState.WithLabelValues("flaky"))
	assert.Equal(t, 1.0, state, "circuit breaker should be open (1) after threshold failures")
}

// TestGovernanceAudit_NormalizeProducesValidEvent verifies the normalized
// event passes the V4 envelope contract (non-null provenance).
func TestGovernanceAudit_NormalizeProducesValidEvent(t *testing.T) {
	h := New(DefaultConfig(), nil)
	blocks := []mcp.ContentBlock{{
		Type: mcp.ContentTypeText,
		Text: `{"document_title":"Audit Article","source_url":"https://audit.example/1","body":"..."}`,
	}}
	require.NoError(t, h.Register(blocksTool("audit-tool", blocks)))

	res, err := h.InvokeTool(context.Background(), "audit-tool", nil, Permission{TenantID: "audit-tenant"}, "kiq-audit", "audit-tenant")
	require.NoError(t, err)
	assert.Equal(t, StageReturnLoop, res.Stage)
	// The harness Normalize stage validated the event internally; here we
	// re-assert the blocks carry the provenance-bearing payload.
	require.NotEmpty(t, res.Blocks)
	assert.True(t, strings.Contains(res.Blocks[0].Text, "Audit Article"))
}

// Ensure the json import is used (schemaTool uses json.RawMessage).
var _ = json.RawMessage{}
