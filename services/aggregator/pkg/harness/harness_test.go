package harness

import (
	"context"
	"encoding/json"
	"errors"
	"sync"
	"testing"
	"time"

	"github.com/omni-g/aggregator/internal/mcp"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// ─── test doubles ───────────────────────────────────────────────────────────

// fakeTool is a configurable Tool for tests.
type fakeTool struct {
	descriptor ToolDescriptor
	invokeFn   func(ctx context.Context, args map[string]any) (<-chan mcp.ContentBlock, error)
}

func (t *fakeTool) Descriptor() ToolDescriptor { return t.descriptor }
func (t *fakeTool) Invoke(ctx context.Context, args map[string]any) (<-chan mcp.ContentBlock, error) {
	return t.invokeFn(ctx, args)
}

// blocksTool returns a tool that streams the given blocks successfully.
func blocksTool(name string, blocks []mcp.ContentBlock) *fakeTool {
	return &fakeTool{
		descriptor: ToolDescriptor{
			Name:        name,
			Description: "test tool",
			Risk:        RiskLow,
			SourceName:  "TestSource",
			SourceURL:   "https://example.com/source",
		},
		invokeFn: func(ctx context.Context, _ map[string]any) (<-chan mcp.ContentBlock, error) {
			ch := make(chan mcp.ContentBlock, len(blocks))
			for _, b := range blocks {
				ch <- b
			}
			close(ch)
			return ch, nil
		},
	}
}

// failTool returns a tool whose Invoke always returns the given error.
func failTool(name string, invokeErr error) *fakeTool {
	return &fakeTool{
		descriptor: ToolDescriptor{Name: name, Risk: RiskLow, SourceName: "TestSource"},
		invokeFn: func(ctx context.Context, _ map[string]any) (<-chan mcp.ContentBlock, error) {
			return nil, invokeErr
		},
	}
}

// schemaTool returns a tool with a JSON-schema inputSchema declaring required fields.
func schemaTool(name string, schemaJSON string, blocks []mcp.ContentBlock) *fakeTool {
	return &fakeTool{
		descriptor: ToolDescriptor{
			Name:        name,
			Risk:        RiskLow,
			SourceName:  "TestSource",
			InputSchema: json.RawMessage(schemaJSON),
		},
		invokeFn: func(ctx context.Context, _ map[string]any) (<-chan mcp.ContentBlock, error) {
			ch := make(chan mcp.ContentBlock, len(blocks))
			for _, b := range blocks {
				ch <- b
			}
			close(ch)
			return ch, nil
		},
	}
}

// fakeClock is a controllable Clock for circuit-breaker tests.
type fakeClock struct {
	mu  sync.Mutex
	now time.Time
}

func newFakeClock() *fakeClock { return &fakeClock{now: time.Date(2026, 8, 11, 12, 0, 0, 0, time.UTC)} }
func (f *fakeClock) Now() time.Time {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.now
}
func (f *fakeClock) Advance(d time.Duration) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.now = f.now.Add(d)
}

// ─── Stage 1: Register ─────────────────────────────────────────────────────

func TestRegister_RejectsEmptyName(t *testing.T) {
	h := New(DefaultConfig(), nil)
	err := h.Register(&fakeTool{descriptor: ToolDescriptor{Risk: RiskLow}})
	require.Error(t, err)
	assert.Contains(t, err.Error(), "stage register")
	assert.Contains(t, err.Error(), "name")
}

func TestRegister_RejectsBadRisk(t *testing.T) {
	h := New(DefaultConfig(), nil)
	err := h.Register(&fakeTool{descriptor: ToolDescriptor{Name: "t", Risk: "extreme"}})
	require.Error(t, err)
	assert.Contains(t, err.Error(), "risk")
}

func TestRegister_RejectsDuplicate(t *testing.T) {
	h := New(DefaultConfig(), nil)
	require.NoError(t, h.Register(blocksTool("dup", nil)))
	err := h.Register(blocksTool("dup", nil))
	require.Error(t, err)
	assert.Contains(t, err.Error(), "already registered")
}

func TestRegister_RejectsBadSchema(t *testing.T) {
	h := New(DefaultConfig(), nil)
	err := h.Register(&fakeTool{descriptor: ToolDescriptor{
		Name:        "bad",
		Risk:        RiskLow,
		InputSchema: json.RawMessage(`{not json`),
	}})
	require.Error(t, err)
	assert.Contains(t, err.Error(), "inputSchema")
}

// ─── Stage 2: Advertise ─────────────────────────────────────────────────────

func TestAdvertise_ReturnsRegisteredTools(t *testing.T) {
	h := New(DefaultConfig(), nil)
	require.NoError(t, h.Register(blocksTool("a", nil)))
	require.NoError(t, h.Register(blocksTool("b", nil)))
	tools := h.Advertise()
	assert.Len(t, tools, 2)
}

// ─── Stage 3: Select ───────────────────────────────────────────────────────

func TestInvokeTool_RejectsUnknownTool(t *testing.T) {
	h := New(DefaultConfig(), nil)
	_, err := h.InvokeTool(context.Background(), "nope", nil, Permission{TenantID: "t"}, "", "t")
	require.Error(t, err)
	assert.Contains(t, err.Error(), "stage select")
	assert.Contains(t, err.Error(), "not registered")
}

// ─── Stage 4: Validate ──────────────────────────────────────────────────────

func TestInvokeTool_RejectsMissingRequiredArg(t *testing.T) {
	schema := `{"type":"object","required":["query"],"properties":{"query":{"type":"string"}}}`
	h := New(DefaultConfig(), nil)
	require.NoError(t, h.Register(schemaTool("search", schema, nil)))
	_, err := h.InvokeTool(context.Background(), "search", map[string]any{}, Permission{TenantID: "t"}, "", "t")
	require.Error(t, err)
	assert.Contains(t, err.Error(), "stage validate")
	assert.Contains(t, err.Error(), "query")
}

func TestInvokeTool_RejectsWrongTypeArg(t *testing.T) {
	schema := `{"type":"object","properties":{"query":{"type":"string"}}}`
	h := New(DefaultConfig(), nil)
	require.NoError(t, h.Register(schemaTool("search", schema, nil)))
	_, err := h.InvokeTool(context.Background(), "search", map[string]any{"query": 123}, Permission{TenantID: "t"}, "", "t")
	require.Error(t, err)
	assert.Contains(t, err.Error(), "stage validate")
	assert.Contains(t, err.Error(), "must be string")
}

func TestInvokeTool_AcceptsValidArgs(t *testing.T) {
	schema := `{"type":"object","required":["query"],"properties":{"query":{"type":"string"}}}`
	blocks := []mcp.ContentBlock{{Type: mcp.ContentTypeText, Text: `{"title":"hello"}`}}
	h := New(DefaultConfig(), nil)
	require.NoError(t, h.Register(schemaTool("search", schema, blocks)))
	res, err := h.InvokeTool(context.Background(), "search", map[string]any{"query": "hi"}, Permission{TenantID: "t"}, "", "t")
	require.NoError(t, err)
	assert.Equal(t, StageReturnLoop, res.Stage)
}

// ─── Stage 5: Permission ────────────────────────────────────────────────────

func TestInvokeTool_PermissionDeniesDisallowedTool(t *testing.T) {
	h := New(DefaultConfig(), nil)
	require.NoError(t, h.Register(blocksTool("secret", []mcp.ContentBlock{{Type: mcp.ContentTypeText, Text: `{"x":1}`}})))
	perm := Permission{TenantID: "restricted", AllowedTools: []string{"other"}}
	_, err := h.InvokeTool(context.Background(), "secret", nil, perm, "", "restricted")
	require.Error(t, err)
	assert.Contains(t, err.Error(), "stage permission")
}

func TestInvokeTool_PermissionAllowsAllWhenEmpty(t *testing.T) {
	h := New(DefaultConfig(), nil)
	require.NoError(t, h.Register(blocksTool("any", []mcp.ContentBlock{{Type: mcp.ContentTypeText, Text: `{"x":1}`}})))
	perm := Permission{TenantID: "default", AllowedTools: nil} // allow-all
	_, err := h.InvokeTool(context.Background(), "any", nil, perm, "", "default")
	require.NoError(t, err)
}

// ─── Stage 6: Execute + circuit breaker ─────────────────────────────────────

func TestInvokeTool_ExecuteFailureReturnsError(t *testing.T) {
	h := New(DefaultConfig(), nil)
	require.NoError(t, h.Register(failTool("boom", errors.New("kaboom"))))
	_, err := h.InvokeTool(context.Background(), "boom", nil, Permission{TenantID: "t"}, "", "t")
	require.Error(t, err)
	assert.Contains(t, err.Error(), "stage execute")
	assert.Contains(t, err.Error(), "kaboom")
}

func TestCircuitBreaker_OpensAfterThresholdFailures(t *testing.T) {
	cfg := DefaultConfig()
	cfg.CircuitBreakerThreshold = 3
	h := New(cfg, nil)
	require.NoError(t, h.Register(failTool("flaky", errors.New("fail"))))

	// First N-1 failures should be plain execute errors.
	for i := 0; i < cfg.CircuitBreakerThreshold-1; i++ {
		_, err := h.InvokeTool(context.Background(), "flaky", nil, Permission{TenantID: "t"}, "", "t")
		require.Error(t, err, "call %d", i)
	}
	// The threshold-reaching failure opens the breaker.
	_, err := h.InvokeTool(context.Background(), "flaky", nil, Permission{TenantID: "t"}, "", "t")
	require.Error(t, err)

	// Now the breaker should be open: a fresh call is rejected at Stage 6
	// with "circuit breaker open", not the underlying tool error.
	_, err = h.InvokeTool(context.Background(), "flaky", nil, Permission{TenantID: "t"}, "", "t")
	require.Error(t, err)
	assert.Contains(t, err.Error(), "stage execute")
	assert.Contains(t, err.Error(), "circuit breaker open")
}

func TestCircuitBreaker_HalfOpenRecovery(t *testing.T) {
	clk := newFakeClock()
	cfg := DefaultConfig()
	cfg.CircuitBreakerThreshold = 2
	cfg.CircuitBreakerReset = 1 * time.Second
	h := New(cfg, clk)

	// Start as a failing tool, then swap to a succeeding tool after the
	// breaker opens. We re-register by using a mutable tool.
	mut := &mutableTool{descriptor: ToolDescriptor{Name: "recover", Risk: RiskLow, SourceName: "S"}}
	require.NoError(t, h.Register(mut))

	// Force failures to open the breaker.
	mut.setErr(errors.New("fail"))
	for i := 0; i < cfg.CircuitBreakerThreshold; i++ {
		_, err := h.InvokeTool(context.Background(), "recover", nil, Permission{TenantID: "t"}, "", "t")
		require.Error(t, err)
	}
	// Breaker is now open.
	_, err := h.InvokeTool(context.Background(), "recover", nil, Permission{TenantID: "t"}, "", "t")
	require.Error(t, err)
	assert.Contains(t, err.Error(), "circuit breaker open")

	// Advance the fake clock past the reset window and make the tool succeed.
	clk.Advance(cfg.CircuitBreakerReset + time.Millisecond)
	mut.setBlocks([]mcp.ContentBlock{{Type: mcp.ContentTypeText, Text: `{"ok":true}`}})

	res, err := h.InvokeTool(context.Background(), "recover", nil, Permission{TenantID: "t"}, "", "t")
	require.NoError(t, err)
	assert.Equal(t, StageReturnLoop, res.Stage)
}

// mutableTool lets a test flip the tool's behaviour between failures and
// successes without re-registering.
type mutableTool struct {
	descriptor ToolDescriptor
	mu         sync.Mutex
	err        error
	blocks     []mcp.ContentBlock
}

func (m *mutableTool) Descriptor() ToolDescriptor { return m.descriptor }
func (m *mutableTool) setErr(e error)             { m.mu.Lock(); defer m.mu.Unlock(); m.err = e }
func (m *mutableTool) setBlocks(b []mcp.ContentBlock) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.blocks = b
	m.err = nil
}
func (m *mutableTool) Invoke(ctx context.Context, _ map[string]any) (<-chan mcp.ContentBlock, error) {
	m.mu.Lock()
	err, blocks := m.err, m.blocks
	m.mu.Unlock()
	if err != nil {
		return nil, err
	}
	ch := make(chan mcp.ContentBlock, len(blocks))
	for _, b := range blocks {
		ch <- b
	}
	close(ch)
	return ch, nil
}

// ─── Stage 8: Normalize ─────────────────────────────────────────────────────

func TestNormalize_ProducesValidEventWithProvenance(t *testing.T) {
	h := New(DefaultConfig(), nil)
	blocks := []mcp.ContentBlock{{
		Type: mcp.ContentTypeText,
		Text: `{"document_title":"PubMed Article","source_url":"https://pubmed/123","body":"..."}`,
	}}
	require.NoError(t, h.Register(blocksTool("news", blocks)))
	res, err := h.InvokeTool(context.Background(), "news", nil, Permission{TenantID: "tenant-a"}, "kiq-1", "tenant-a")
	require.NoError(t, err)
	assert.Equal(t, StageReturnLoop, res.Stage)
	assert.NotEmpty(t, res.Blocks)
}

func TestNormalize_RejectsEmptyBlocks(t *testing.T) {
	h := New(DefaultConfig(), nil)
	require.NoError(t, h.Register(blocksTool("empty", nil)))
	_, err := h.InvokeTool(context.Background(), "empty", nil, Permission{TenantID: "t"}, "", "t")
	require.Error(t, err)
	assert.Contains(t, err.Error(), "stage normalize")
}

// ─── Full happy path ────────────────────────────────────────────────────────

func TestInvokeTool_FullHappyPath_AllStagesRun(t *testing.T) {
	h := New(DefaultConfig(), nil)
	blocks := []mcp.ContentBlock{{
		Type: mcp.ContentTypeText,
		Text: `{"title":"Hello","source_url":"https://example.com/hello"}`,
	}}
	require.NoError(t, h.Register(blocksTool("happy", blocks)))

	res, err := h.InvokeTool(context.Background(), "happy", nil, Permission{TenantID: "tenant-a"}, "kiq-9", "tenant-a")
	require.NoError(t, err)
	require.NotNil(t, res)
	assert.Equal(t, StageReturnLoop, res.Stage)
	assert.Equal(t, "happy", res.Tool.Name)
	assert.NotEmpty(t, res.Blocks)
	assert.Greater(t, res.Latency, 0.0)
}
