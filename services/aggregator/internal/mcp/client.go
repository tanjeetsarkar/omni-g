package mcp

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

// Client calls an MCP plugin server using JSON-RPC 2.0 over HTTP.
// Tool-call responses are delivered as Server-Sent Events (SSE).
type Client struct {
	http    *http.Client
	baseURL string
}

// NewClient constructs a Client for the MCP plugin server at baseURL.
func NewClient(baseURL string) *Client {
	return &Client{
		baseURL: strings.TrimRight(baseURL, "/"),
		http: &http.Client{
			Timeout: 30 * time.Second,
		},
	}
}

// ListTools calls the plugin's "tools/list" method and returns the available
// tools.
func (c *Client) ListTools(ctx context.Context) ([]Tool, error) {
	req := JSONRPCRequest{
		JSONRPC: "2.0",
		ID:      1,
		Method:  "tools/list",
	}

	resp, err := c.call(ctx, req)
	if err != nil {
		return nil, err
	}
	if resp.Error != nil {
		return nil, fmt.Errorf("tools/list error %d: %s", resp.Error.Code, resp.Error.Message)
	}

	var result ToolsListResult
	if err := json.Unmarshal(resp.Result, &result); err != nil {
		return nil, fmt.Errorf("decode tools/list result: %w", err)
	}

	return result.Tools, nil
}

// CallTool invokes a named tool with the given arguments and returns a channel
// that receives ContentBlocks streamed over SSE. The channel is closed when the
// stream ends or ctx is cancelled.
func (c *Client) CallTool(ctx context.Context, name string, args map[string]any) (<-chan ContentBlock, error) {
	params := ToolCallParams{Name: name, Arguments: args}
	paramsJSON, err := json.Marshal(params)
	if err != nil {
		return nil, fmt.Errorf("marshal tool call params: %w", err)
	}

	req := JSONRPCRequest{
		JSONRPC: "2.0",
		ID:      2,
		Method:  "tools/call",
		Params:  json.RawMessage(paramsJSON),
	}

	body, err := json.Marshal(req)
	if err != nil {
		return nil, fmt.Errorf("marshal jsonrpc request: %w", err)
	}

	httpReq, err := http.NewRequestWithContext(ctx, http.MethodPost, c.baseURL+"/sse", bytes.NewReader(body))
	if err != nil {
		return nil, fmt.Errorf("build sse request: %w", err)
	}
	httpReq.Header.Set("Content-Type", "application/json")
	httpReq.Header.Set("Accept", "text/event-stream")

	// Use a client without timeout for SSE streaming.
	sseClient := &http.Client{}
	httpResp, err := sseClient.Do(httpReq)
	if err != nil {
		return nil, fmt.Errorf("call sse endpoint: %w", err)
	}

	if httpResp.StatusCode != http.StatusOK {
		raw, _ := io.ReadAll(io.LimitReader(httpResp.Body, 4096))
		httpResp.Body.Close()
		return nil, fmt.Errorf("unexpected sse status %d: %s", httpResp.StatusCode, raw)
	}

	ch := make(chan ContentBlock, 16)

	go func() {
		// Ensure the body is closed when the context is cancelled, which
		// unblocks any in-progress bufio.Scanner.Scan() call.
		go func() {
			<-ctx.Done()
			httpResp.Body.Close()
		}()
		defer close(ch)
		parseSSE(ctx, httpResp.Body, ch)
		httpResp.Body.Close() // also close on natural stream end
	}()

	return ch, nil
}

// ─── helpers ─────────────────────────────────────────────────────────────────

// call performs a standard JSON-RPC HTTP POST (non-streaming).
func (c *Client) call(ctx context.Context, req JSONRPCRequest) (*JSONRPCResponse, error) {
	body, err := json.Marshal(req)
	if err != nil {
		return nil, fmt.Errorf("marshal request: %w", err)
	}

	httpReq, err := http.NewRequestWithContext(ctx, http.MethodPost, c.baseURL, bytes.NewReader(body))
	if err != nil {
		return nil, fmt.Errorf("build request: %w", err)
	}
	httpReq.Header.Set("Content-Type", "application/json")

	httpResp, err := c.http.Do(httpReq)
	if err != nil {
		return nil, fmt.Errorf("http post: %w", err)
	}
	defer httpResp.Body.Close()

	if httpResp.StatusCode != http.StatusOK {
		raw, _ := io.ReadAll(io.LimitReader(httpResp.Body, 4096))
		return nil, fmt.Errorf("unexpected status %d: %s", httpResp.StatusCode, raw)
	}

	var resp JSONRPCResponse
	if err := json.NewDecoder(httpResp.Body).Decode(&resp); err != nil {
		return nil, fmt.Errorf("decode response: %w", err)
	}

	return &resp, nil
}

// parseSSE reads SSE lines from r and sends ContentBlocks to ch until the
// stream ends or ctx is cancelled.
//
// Expected event format:
//
//	data: {"type":"text","text":"..."}
func parseSSE(ctx context.Context, r io.Reader, ch chan<- ContentBlock) {
	scanner := bufio.NewScanner(r)
	for scanner.Scan() {
		select {
		case <-ctx.Done():
			return
		default:
		}

		line := scanner.Text()
		if !strings.HasPrefix(line, "data:") {
			continue
		}

		payload := strings.TrimSpace(strings.TrimPrefix(line, "data:"))
		if payload == "[DONE]" {
			return
		}

		var block ContentBlock
		if err := json.Unmarshal([]byte(payload), &block); err != nil {
			continue // skip malformed events
		}

		select {
		case ch <- block:
		case <-ctx.Done():
			return
		}
	}
}
