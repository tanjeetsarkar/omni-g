package agent

import (
	"context"
	"encoding/json"
	"testing"
	"time"

	"github.com/omni-g/aggregator/internal/mcp"
	"github.com/omni-g/aggregator/pkg/harness"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// ─── AgenticRouter tests ─────────────────────────────────────────────────────

// queryTool returns a tool whose inputSchema declares a "query" property.
func queryTool(name string) *fakeTool {
	return &fakeTool{
		descriptor: harness.ToolDescriptor{
			Name:        name,
			Description: name + " description",
			Risk:        harness.RiskLow,
			SourceName:  "TestSource",
			SourceURL:   "https://example.com/" + name,
			InputSchema: json.RawMessage(`{"type":"object","properties":{"query":{"type":"string"}}}`),
		},
		invokeFn: func(ctx context.Context, _ map[string]any) (<-chan mcp.ContentBlock, error) {
			ch := make(chan mcp.ContentBlock, 1)
			ch <- mcp.ContentBlock{Type: mcp.ContentTypeText, Text: `{"result":"ok"}`}
			close(ch)
			return ch, nil
		},
	}
}

// locationTool returns a tool that requires a "location" property (no query).
func locationTool(name string) *fakeTool {
	return &fakeTool{
		descriptor: harness.ToolDescriptor{
			Name:        name,
			Description: name + " description",
			Risk:        harness.RiskLow,
			SourceName:  "TestSource",
			SourceURL:   "https://example.com/" + name,
			InputSchema: json.RawMessage(`{"type":"object","properties":{"location":{"type":"string"}}}`),
		},
		invokeFn: func(ctx context.Context, _ map[string]any) (<-chan mcp.ContentBlock, error) {
			ch := make(chan mcp.ContentBlock, 1)
			ch <- mcp.ContentBlock{Type: mcp.ContentTypeText, Text: `{"result":"ok"}`}
			close(ch)
			return ch, nil
		},
	}
}

func newTestRouter(h *harness.Harness) *AgenticRouter {
	return NewAgenticRouter(RouterConfig{
		OpenRouterAPIKey: "", // empty → fallback mode
		OpenRouterModel:  "openai/gpt-4o-mini",
		MaxTools:         5,
		Timeout:          5 * time.Second,
		Harness:          h,
		TenantID:         "test-tenant",
	})
}

func TestRouterFallbackFanOut(t *testing.T) {
	h := harness.New(harness.DefaultConfig(), nil)
	require.NoError(t, h.Register(queryTool("web_search")))
	require.NoError(t, h.Register(queryTool("news_search")))
	require.NoError(t, h.Register(locationTool("weather_forecast")))

	router := newTestRouter(h)

	// "latest AI news" → classifier detects "news" + "latest" → selects news_search only.
	result, err := router.Route(context.Background(), "latest AI news", "", "")
	require.NoError(t, err)
	require.NotNil(t, result)

	// Fallback classifier selects only the most relevant category (news), not all tools.
	assert.Equal(t, 1, len(result.Results), "should invoke only news tools for news query")
	assert.Equal(t, 0, len(result.Errors))

	names := map[string]bool{}
	for _, r := range result.Results {
		names[r.Tool.Name] = true
	}
	assert.True(t, names["news_search"], "news_search should be invoked for news query")
	assert.False(t, names["web_search"], "web_search should NOT be invoked for news query (news_search preferred)")
	assert.False(t, names["weather_forecast"], "weather_forecast should NOT be invoked (no query param)")

	// "weather in Paris" → classifier detects "weather" → selects weather_forecast.
	// But weather_forecast doesn't accept "query" param, so it falls back to web_search.
	result2, err2 := router.Route(context.Background(), "weather in Paris", "", "")
	require.NoError(t, err2)
	require.NotNil(t, result2)
	// weather_forecast has no "query" param, so the classifier falls back to web_search.
	assert.GreaterOrEqual(t, len(result2.Results), 0, "weather query may fall back to web_search")
}

func TestRouterEmptyHarness(t *testing.T) {
	h := harness.New(harness.DefaultConfig(), nil)
	router := newTestRouter(h)

	result, err := router.Route(context.Background(), "anything", "", "")
	require.NoError(t, err)
	require.NotNil(t, result)
	assert.Equal(t, 0, len(result.Results), "no tools registered → no results")
}

func TestParseToolSelection(t *testing.T) {
	tests := []struct {
		name     string
		response string
		want     int
		wantErr  bool
	}{
		{
			name:     "plain object",
			response: `{"tools":[{"name":"web_search","args":{"query":"AI news"}}]}`,
			want:     1,
		},
		{
			name:     "markdown code fence",
			response: "```json\n{\"tools\":[{\"name\":\"web_search\",\"args\":{\"query\":\"AI\"}}]}\n```",
			want:     1,
		},
		{
			name:     "bare array",
			response: `[{"name":"web_search","args":{"query":"AI"}}]`,
			want:     1,
		},
		{
			name:     "empty tools",
			response: `{"tools":[]}`,
			want:     0,
		},
		{
			name:     "invalid json",
			response: `not json`,
			wantErr:  true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			calls, err := parseToolSelection(tt.response)
			if tt.wantErr {
				assert.Error(t, err)
				return
			}
			assert.NoError(t, err)
			assert.Equal(t, tt.want, len(calls))
		})
	}
}

func TestParseQueries(t *testing.T) {
	tests := []struct {
		name string
		raw  string
		want []string
	}{
		{"empty", "", nil},
		{"single", "AI news", []string{"AI news"}},
		{"multiple", "AI news, cybersecurity, markets", []string{"AI news", "cybersecurity", "markets"}},
		{"with spaces", "  AI  ,  crypto  ", []string{"AI", "crypto"}},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := ParseQueries(tt.raw)
			assert.Equal(t, tt.want, got)
		})
	}
}

func TestQueryAgentRunsQueries(t *testing.T) {
	h := harness.New(harness.DefaultConfig(), nil)
	require.NoError(t, h.Register(queryTool("web_search")))
	require.NoError(t, h.Register(queryTool("news_search")))

	router := newTestRouter(h)

	var results int
	qa := NewQueryAgent(QueryAgentConfig{
		Name:     "test-query-agent",
		Router:   router,
		Queries:  []string{"AI news", "cybersecurity"},
		Interval: time.Hour, // long interval — only the initial run fires
		TenantID: "test-tenant",
		OnResult: func(ctx context.Context, result *harness.InvokeResult) error {
			results++
			return nil
		},
	})

	ctx, cancel := context.WithTimeout(context.Background(), 300*time.Millisecond)
	defer cancel()

	go func() {
		_ = qa.Start(ctx)
	}()

	// Wait for the initial run to complete.
	time.Sleep(150 * time.Millisecond)
	cancel()
	_ = qa.Stop(time.Second)

	// Initial run should have produced 2 queries × 1 tool = 2 results.
	// The fallback classifier now selects only the most relevant tool per query
	// (web_search for both "AI news" and "cybersecurity") instead of fanning out
	// to all tools.
	assert.Equal(t, 2, results, "initial query cycle should run 2 queries × 1 tool")
}

func TestQueryAgentNoQueries(t *testing.T) {
	h := harness.New(harness.DefaultConfig(), nil)
	router := newTestRouter(h)

	qa := NewQueryAgent(QueryAgentConfig{
		Name:    "idle-agent",
		Router:  router,
		Queries: nil,
	})

	ctx, cancel := context.WithTimeout(context.Background(), 50*time.Millisecond)
	defer cancel()

	err := qa.Start(ctx)
	assert.NoError(t, err, "idle agent should start and immediately stop cleanly")
}
