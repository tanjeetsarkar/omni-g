package agent

import (
	"context"
	"encoding/json"
	"errors"
	"sync/atomic"
	"testing"
	"time"

	"github.com/omni-g/aggregator/internal/mcp"
	"github.com/omni-g/aggregator/pkg/harness"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// ─── shared test helpers ───────────────────────────────────────────────────

// fakeTool is a configurable harness.Tool for agent tests.
type fakeTool struct {
	descriptor harness.ToolDescriptor
	invokeFn   func(ctx context.Context, args map[string]any) (<-chan mcp.ContentBlock, error)
}

func (t *fakeTool) Descriptor() harness.ToolDescriptor { return t.descriptor }
func (t *fakeTool) Invoke(ctx context.Context, args map[string]any) (<-chan mcp.ContentBlock, error) {
	return t.invokeFn(ctx, args)
}

// blocksTool returns a tool that streams the given blocks successfully.
func blocksTool(name string, blocks []mcp.ContentBlock) *fakeTool {
	return &fakeTool{
		descriptor: harness.ToolDescriptor{
			Name:       name,
			Risk:       harness.RiskLow,
			SourceName: "TestSource",
			SourceURL:  "https://example.com/source",
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

// schemaTool returns a tool with a required-param inputSchema (skipped by poller).
func schemaTool(name string) *fakeTool {
	return &fakeTool{
		descriptor: harness.ToolDescriptor{
			Name:        name,
			Risk:        harness.RiskLow,
			SourceName:  "TestSource",
			InputSchema: json.RawMessage(`{"type":"object","required":["query"],"properties":{"query":{"type":"string"}}}`),
		},
		invokeFn: func(ctx context.Context, _ map[string]any) (<-chan mcp.ContentBlock, error) {
			ch := make(chan mcp.ContentBlock, 1)
			ch <- mcp.ContentBlock{Type: mcp.ContentTypeText, Text: `{"x":1}`}
			close(ch)
			return ch, nil
		},
	}
}

// failTool returns a tool whose Invoke always errors.
func failTool(name string, err error) *fakeTool {
	return &fakeTool{
		descriptor: harness.ToolDescriptor{Name: name, Risk: harness.RiskLow, SourceName: "TestSource"},
		invokeFn: func(ctx context.Context, _ map[string]any) (<-chan mcp.ContentBlock, error) {
			return nil, err
		},
	}
}

// newHarnessWith builds a harness with the given tools registered.
func newHarnessWith(tools ...harness.Tool) *harness.Harness {
	h := harness.New(harness.DefaultConfig(), nil)
	for _, t := range tools {
		if err := h.Register(t); err != nil {
			panic(err)
		}
	}
	return h
}

// ─── PollerAgent ────────────────────────────────────────────────────────────

func TestPollerAgent_PollsAndForwardsBlocks(t *testing.T) {
	blocks := []mcp.ContentBlock{{Type: mcp.ContentTypeText, Text: `{"title":"hello"}`}}
	h := newHarnessWith(blocksTool("news", blocks))

	var received atomic.Int32
	poller := NewPollerAgent(PollerConfig{
		Name:     "poller-1",
		Harness:  h,
		Interval: 50 * time.Millisecond,
		TenantID: "tenant-a",
		OnResult: func(ctx context.Context, r *harness.InvokeResult) error {
			received.Add(1)
			assert.NotEmpty(t, r.Blocks)
			return nil
		},
	})

	ctx, cancel := context.WithTimeout(context.Background(), 500*time.Millisecond)
	defer cancel()
	require.NoError(t, poller.Start(ctx))
	<-ctx.Done()
	_ = poller.Stop(2 * time.Second)

	assert.GreaterOrEqual(t, received.Load(), int32(1), "poller should have forwarded at least one result")
	hlth := poller.Health()
	assert.Equal(t, StatusStopped, hlth.Status)
}

func TestPollerAgent_SkipsRequiredParamTools(t *testing.T) {
	h := newHarnessWith(schemaTool("needs-query"))
	var received atomic.Int32
	poller := NewPollerAgent(PollerConfig{
		Name:     "poller-skip",
		Harness:  h,
		Interval: 50 * time.Millisecond,
		TenantID: "t",
		OnResult: func(ctx context.Context, r *harness.InvokeResult) error {
			received.Add(1)
			return nil
		},
	})
	ctx, cancel := context.WithTimeout(context.Background(), 200*time.Millisecond)
	defer cancel()
	require.NoError(t, poller.Start(ctx))
	<-ctx.Done()
	_ = poller.Stop(time.Second)
	assert.Equal(t, int32(0), received.Load(), "poller must not call required-param tools")
}

func TestPollerAgent_RecordsErrorsOnFailure(t *testing.T) {
	h := newHarnessWith(failTool("boom", errors.New("kaboom")))
	poller := NewPollerAgent(PollerConfig{
		Name:     "poller-fail",
		Harness:  h,
		Interval: 50 * time.Millisecond,
		TenantID: "t",
	})
	ctx, cancel := context.WithTimeout(context.Background(), 300*time.Millisecond)
	defer cancel()
	require.NoError(t, poller.Start(ctx))
	<-ctx.Done()
	_ = poller.Stop(time.Second)
	hlth := poller.Health()
	assert.Greater(t, hlth.ErrorCount, 0)
	assert.Contains(t, hlth.LastError, "kaboom")
}

// ─── WatcherAgent ──────────────────────────────────────────────────────────

func TestWatcherAgent_ForwardsBlocksAndReconnects(t *testing.T) {
	blocks := []mcp.ContentBlock{{Type: mcp.ContentTypeText, Text: `{"x":1}`}}
	h := newHarnessWith(blocksTool("stream", blocks))

	var received atomic.Int32
	watcher := NewWatcherAgent(WatcherConfig{
		Name:     "watcher-1",
		Harness:  h,
		ToolName: "stream",
		TenantID: "t",
		OnResult: func(ctx context.Context, r *harness.InvokeResult) error { received.Add(1); return nil },
	})

	ctx, cancel := context.WithTimeout(context.Background(), 300*time.Millisecond)
	defer cancel()
	require.NoError(t, watcher.Start(ctx))
	<-ctx.Done()
	_ = watcher.Stop(time.Second)
	assert.GreaterOrEqual(t, received.Load(), int32(1), "watcher should forward at least one result")
}

func TestWatcherAgent_StopsOnNonRetryableRejection(t *testing.T) {
	// Unknown tool → Stage 3 rejection (non-retryable).
	h := newHarnessWith()
	watcher := NewWatcherAgent(WatcherConfig{
		Name:     "watcher-bad",
		Harness:  h,
		ToolName: "does-not-exist",
		TenantID: "t",
	})
	ctx, cancel := context.WithTimeout(context.Background(), 200*time.Millisecond)
	defer cancel()
	require.NoError(t, watcher.Start(ctx))
	<-ctx.Done()
	_ = watcher.Stop(time.Second)
	hlth := watcher.Health()
	assert.Greater(t, hlth.ErrorCount, 0)
	assert.Contains(t, hlth.LastError, "not registered")
}

// ─── AgentSupervisor ────────────────────────────────────────────────────────

func TestSupervisor_StartsAndStopsAllAgents(t *testing.T) {
	blocks := []mcp.ContentBlock{{Type: mcp.ContentTypeText, Text: `{"x":1}`}}
	h := newHarnessWith(blocksTool("news", blocks))

	p1 := NewPollerAgent(PollerConfig{Name: "p1", Harness: h, Interval: 50 * time.Millisecond, TenantID: "t"})
	p2 := NewPollerAgent(PollerConfig{Name: "p2", Harness: h, Interval: 50 * time.Millisecond, TenantID: "t"})

	sup := NewSupervisor(SupervisorConfig{HealthTick: 50 * time.Millisecond, RestartMax: 2})
	sup.Register(p1)
	sup.Register(p2)

	ctx, cancel := context.WithTimeout(context.Background(), 300*time.Millisecond)
	defer cancel()
	require.NoError(t, sup.Start(ctx))
	<-ctx.Done()
	require.NoError(t, sup.Stop())

	health := sup.Health()
	assert.Contains(t, health, "p1")
	assert.Contains(t, health, "p2")
}

func TestSupervisor_RestartsCrashedAgent(t *testing.T) {
	// A tool that fails immediately so the poller's pollOnce errors, but the
	// agent goroutine keeps looping (poller doesn't exit on errors). To test
	// supervisor restart we need an agent that *stops*. Use a watcher on an
	// unknown tool — it exits immediately on non-retryable rejection.
	h := newHarnessWith()
	w := NewWatcherAgent(WatcherConfig{
		Name:     "crashy-watcher",
		Harness:  h,
		ToolName: "nope",
		TenantID: "t",
	})

	sup := NewSupervisor(SupervisorConfig{HealthTick: 20 * time.Millisecond, RestartMax: 2})
	sup.Register(w)

	ctx, cancel := context.WithTimeout(context.Background(), 400*time.Millisecond)
	defer cancel()
	require.NoError(t, sup.Start(ctx))
	<-ctx.Done()
	require.NoError(t, sup.Stop())

	// The supervisor should have attempted restarts (recorded internally).
	sup.mu.Lock()
	restarts := sup.restarts["crashy-watcher"]
	sup.mu.Unlock()
	assert.Greater(t, restarts, 0, "supervisor should have restarted the crashed watcher")
}
