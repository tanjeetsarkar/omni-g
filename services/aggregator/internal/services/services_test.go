package services

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/omni-g/aggregator/internal/mcp"
	"github.com/omni-g/aggregator/pkg/harness"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// mockPlugin returns a test MCP plugin server that responds to tools/list and
// /sse (tools/call) with the given SSE blocks.
func mockPlugin(t *testing.T, sseBlocks []mcp.ContentBlock) *httptest.Server {
	t.Helper()
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/sse" {
			w.Header().Set("Content-Type", "text/event-stream")
			w.WriteHeader(http.StatusOK)
			flusher, ok := w.(http.Flusher)
			require.True(t, ok)
			for _, b := range sseBlocks {
				data, _ := json.Marshal(b)
				_, _ = w.Write([]byte("data: " + string(data) + "\n\n"))
				flusher.Flush()
			}
			_, _ = w.Write([]byte("data: [DONE]\n\n"))
			flusher.Flush()
			return
		}
		// tools/list
		var req mcp.JSONRPCRequest
		require.NoError(t, json.NewDecoder(r.Body).Decode(&req))
		result, _ := json.Marshal(mcp.ToolsListResult{Tools: []mcp.Tool{{Name: "search_news"}}})
		resp := mcp.JSONRPCResponse{JSONRPC: "2.0", ID: req.ID, Result: json.RawMessage(result)}
		w.Header().Set("Content-Type", "application/json")
		require.NoError(t, json.NewEncoder(w).Encode(resp))
	}))
}

// ─── registration tests ────────────────────────────────────────────────────

func TestAllServices_RegisterWithHarness(t *testing.T) {
	cfg := ServiceConfig{
		NewsRSSPluginURL:   "http://newsrss:8090",
		ReutersPluginURL:   "http://reuters:8091",
		WikipediaPluginURL: "http://wiki:8092",
		WikidataPluginURL:  "http://wikidata:8093",
	}
	h := harness.New(harness.DefaultConfig(), nil)
	for _, svc := range All(cfg) {
		require.NoError(t, svc.Register(h), "service %s failed to register", svc.Name())
	}
	advertised := h.Advertise()
	names := make(map[string]bool, len(advertised))
	for _, d := range advertised {
		names[d.Name] = true
	}
	assert.True(t, names["search_news"], "news service should register search_news")
	assert.True(t, names["web_search"], "search service should register web_search")
	assert.True(t, names["fetch_weather"], "weather service should register fetch_weather")
	assert.True(t, names["fetch_feed"], "feeds service should register fetch_feed")
}

// ─── News + Search invocation tests ─────────────────────────────────────────

func TestNewsService_InvokeReturnsBlocks(t *testing.T) {
	blocks := []mcp.ContentBlock{{Type: mcp.ContentTypeText, Text: `{"title":"headline","source_url":"https://news/1"}`}}
	srv := mockPlugin(t, blocks)
	defer srv.Close()

	cfg := ServiceConfig{NewsRSSPluginURL: srv.URL, ReutersPluginURL: srv.URL}
	h := harness.New(harness.DefaultConfig(), nil)
	require.NoError(t, NewNewsService(cfg).Register(h))

	res, err := h.InvokeTool(context.Background(), "search_news", map[string]any{"query": "test"},
		harness.Permission{TenantID: "t"}, "", "t")
	require.NoError(t, err)
	assert.NotEmpty(t, res.Blocks)
}

func TestSearchService_InvokeReturnsBlocks(t *testing.T) {
	blocks := []mcp.ContentBlock{{Type: mcp.ContentTypeText, Text: `{"title":"wiki article","source_url":"https://wiki/1"}`}}
	srv := mockPlugin(t, blocks)
	defer srv.Close()

	cfg := ServiceConfig{WikipediaPluginURL: srv.URL, WikidataPluginURL: srv.URL}
	h := harness.New(harness.DefaultConfig(), nil)
	require.NoError(t, NewSearchService(cfg).Register(h))

	res, err := h.InvokeTool(context.Background(), "web_search", map[string]any{"query": "test"},
		harness.Permission{TenantID: "t"}, "", "t")
	require.NoError(t, err)
	assert.NotEmpty(t, res.Blocks)
}

// ─── Weather (wttr.in) tests ────────────────────────────────────────────────

func TestWeatherService_FetchesFromWttrIn(t *testing.T) {
	// Stand up a fake wttr.in server returning a minimal valid JSON payload.
	wttrPayload := `{
		"current_condition": [
			{
				"temp_C": "19", "FeelsLikeC": "17", "humidity": "67",
				"windspeedKmph": "13", "winddir16Point": "NE",
				"weatherDesc": [{"value": "Clear"}],
				"observation_time": "03:50 AM"
			}
		],
		"nearest_area": [
			{
				"areaName": [{"value": "Paris"}],
				"country": [{"value": "France"}],
				"latitude": "48.85", "longitude": "2.35"
			}
		]
	}`
	wttrSrv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(wttrPayload))
	}))
	defer wttrSrv.Close()

	// Override the package-level wttr config for this test.
	origBase := wttrBaseURL
	origClient := wttrHTTPClient
	origLimiter := sharedWttrLimiter
	wttrBaseURL = wttrSrv.URL
	wttrHTTPClient = &http.Client{Timeout: 5 * time.Second}
	sharedWttrLimiter = newWttrRateLimiter(2, 1*time.Millisecond) // fast for tests
	defer func() {
		wttrBaseURL = origBase
		wttrHTTPClient = origClient
		sharedWttrLimiter = origLimiter
	}()

	h := harness.New(harness.DefaultConfig(), nil)
	require.NoError(t, NewWeatherService(ServiceConfig{}).Register(h))

	res, err := h.InvokeTool(context.Background(), "fetch_weather", map[string]any{"location": "Paris"},
		harness.Permission{TenantID: "t"}, "", "t")
	require.NoError(t, err)
	require.NotEmpty(t, res.Blocks)
	// The normalized block should carry wttr.in provenance + parsed fields.
	assert.Contains(t, res.Blocks[0].Text, "wttr.in")
	assert.Contains(t, res.Blocks[0].Text, "Paris")
	assert.Contains(t, res.Blocks[0].Text, "Clear")
	assert.Contains(t, res.Blocks[0].Text, "19")
}

func TestWeatherService_RateLimiterEnforcesInterval(t *testing.T) {
	// The rate limiter should serialise calls; with a 50ms min-interval two
	// sequential calls should take at least 50ms total.
	limiter := newWttrRateLimiter(1, 50*time.Millisecond)
	ctx := context.Background()
	start := time.Now()
	require.NoError(t, limiter.acquire(ctx))
	limiter.release()
	require.NoError(t, limiter.acquire(ctx))
	limiter.release()
	elapsed := time.Since(start)
	assert.GreaterOrEqual(t, elapsed, 50*time.Millisecond, "rate limiter should enforce min-interval")
}

// ─── Feeds service ─────────────────────────────────────────────────────────

func TestFeedsService_InvokeReturnsBlocks(t *testing.T) {
	blocks := []mcp.ContentBlock{{Type: mcp.ContentTypeText, Text: `{"title":"feed item","source_url":"https://feed/1"}`}}
	srv := mockPlugin(t, blocks)
	defer srv.Close()

	cfg := ServiceConfig{NewsRSSPluginURL: srv.URL}
	h := harness.New(harness.DefaultConfig(), nil)
	require.NoError(t, NewFeedsService(cfg).Register(h))

	res, err := h.InvokeTool(context.Background(), "fetch_feed", map[string]any{"query": "tech"},
		harness.Permission{TenantID: "t"}, "", "t")
	require.NoError(t, err)
	assert.NotEmpty(t, res.Blocks)
}
