package scheduler_test

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/omni-g/aggregator/internal/mcp"
	"github.com/omni-g/aggregator/internal/scheduler"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// mockPlugin returns a test HTTP server that responds to tools/list and /sse
// (tools/call SSE) with the provided tools and SSE blocks.
func mockPlugin(t *testing.T, tools []mcp.Tool, sseBlocks []mcp.ContentBlock) *httptest.Server {
	t.Helper()
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/sse" {
			// SSE tool-call response
			w.Header().Set("Content-Type", "text/event-stream")
			w.WriteHeader(http.StatusOK)
			flusher, ok := w.(http.Flusher)
			require.True(t, ok)
			for _, b := range sseBlocks {
				data, _ := json.Marshal(b)
				fmt.Fprintf(w, "data: %s\n\n", data)
				flusher.Flush()
			}
			fmt.Fprintf(w, "data: [DONE]\n\n")
			flusher.Flush()
			return
		}

		// tools/list
		var req mcp.JSONRPCRequest
		require.NoError(t, json.NewDecoder(r.Body).Decode(&req))

		result, _ := json.Marshal(mcp.ToolsListResult{Tools: tools})
		resp := mcp.JSONRPCResponse{JSONRPC: "2.0", ID: req.ID, Result: json.RawMessage(result)}
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(resp)
	}))
}

func TestScheduler_ReceivesBlocks(t *testing.T) {
	expected := []mcp.ContentBlock{
		{Type: mcp.ContentTypeText, Text: `{"ip":"1.2.3.4"}`},
	}

	srv := mockPlugin(t,
		[]mcp.Tool{{Name: "echo", Description: "echo"}},
		expected,
	)
	defer srv.Close()

	s := scheduler.New()
	s.RegisterPlugin(srv.URL, 100*time.Millisecond)

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	var received atomic.Int32
	go s.Start(ctx, func(_ context.Context, _ string, block mcp.ContentBlock) error {
		received.Add(1)
		assert.Equal(t, mcp.ContentTypeText, block.Type)
		return nil
	})

	// Wait until at least one block is delivered, then cancel.
	require.Eventually(t, func() bool {
		return received.Load() >= 1
	}, 2*time.Second, 50*time.Millisecond)

	cancel()
}

func TestScheduler_MultiplePlugins(t *testing.T) {
	block := mcp.ContentBlock{Type: mcp.ContentTypeText, Text: "data"}
	srv1 := mockPlugin(t, []mcp.Tool{{Name: "t1"}}, []mcp.ContentBlock{block})
	srv2 := mockPlugin(t, []mcp.Tool{{Name: "t2"}}, []mcp.ContentBlock{block})
	defer srv1.Close()
	defer srv2.Close()

	s := scheduler.New()
	s.RegisterPlugin(srv1.URL, 50*time.Millisecond)
	s.RegisterPlugin(srv2.URL, 50*time.Millisecond)

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	sources := make(map[string]int)
	var mu sync.Mutex

	go s.Start(ctx, func(_ context.Context, source string, _ mcp.ContentBlock) error {
		mu.Lock()
		sources[source]++
		mu.Unlock()
		return nil
	})

	require.Eventually(t, func() bool {
		mu.Lock()
		defer mu.Unlock()
		return sources[srv1.URL] >= 1 && sources[srv2.URL] >= 1
	}, 2*time.Second, 50*time.Millisecond)

	cancel()
}

func TestScheduler_NoPlugins(t *testing.T) {
	s := scheduler.New()
	ctx, cancel := context.WithTimeout(context.Background(), 200*time.Millisecond)
	defer cancel()

	// Should return quickly when no plugins registered.
	done := make(chan struct{})
	go func() {
		s.Start(ctx, func(_ context.Context, _ string, _ mcp.ContentBlock) error { return nil })
		close(done)
	}()

	select {
	case <-done:
		// expected
	case <-time.After(500 * time.Millisecond):
		t.Fatal("Start did not return after ctx cancel with no plugins")
	}
}

func TestScheduler_PluginUnavailable_DoesNotPanic(t *testing.T) {
	s := scheduler.New()
	s.RegisterPlugin("http://localhost:1", 50*time.Millisecond) // nothing listening

	ctx, cancel := context.WithTimeout(context.Background(), 500*time.Millisecond)
	defer cancel()

	// Should not panic; just log errors and back off.
	done := make(chan struct{})
	go func() {
		s.Start(ctx, func(_ context.Context, _ string, _ mcp.ContentBlock) error { return nil })
		close(done)
	}()

	select {
	case <-done:
	case <-time.After(2 * time.Second):
		t.Fatal("Start did not return after ctx cancel")
	}
}
