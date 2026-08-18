package mcp

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

	"github.com/rs/zerolog/log"
)

// Client calls an MCP plugin server using JSON-RPC 2.0 over HTTP.
// Tool-call responses are delivered as Server-Sent Events (SSE).
type Client struct {
	http    *http.Client
	baseURL string
	headers http.Header // per-request headers (e.g. Authorization)
}

// NewClient constructs a Client for the MCP plugin server at baseURL.
// No custom headers are sent.
func NewClient(baseURL string) *Client {
	return NewClientWithHeaders(baseURL, nil)
}

// NewClientWithHeaders constructs a Client that attaches the given headers to
// every request. headers may be nil (no extra headers).
func NewClientWithHeaders(baseURL string, headers http.Header) *Client {
	return &Client{
		baseURL: strings.TrimRight(baseURL, "/"),
		headers: headers,
		http: &http.Client{
			Timeout: 30 * time.Second,
		},
	}
}

// ListTools calls the plugin's "tools/list" method and returns the available
// tools.
func (c *Client) ListTools(ctx context.Context) ([]Tool, error) {
	logger := log.With().Str("plugin_url", c.baseURL).Str("method", "tools/list").Logger()

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
	logger.Debug().Int("tool_count", len(result.Tools)).Msg("tools/list completed")

	return result.Tools, nil
}

// CallTool invokes a named tool with the given arguments and returns a channel
// that receives the ContentBlocks from the JSON-RPC tools/call response.
//
// Mu (and any go-micro gateway/mcp server) serves tools/call at the same
// endpoint as tools/list — a single POST returning one application/json
// JSON-RPC response whose result.content[] carries the text blocks. There is
// no SSE stream for tool calls; the channel is closed once the response is
// decoded and all blocks have been delivered.
//
// A tool-level failure (mu returns result.isError=true with a text block
// describing the failure, e.g. "Search query required") is delivered as a
// ContentBlock rather than converted to a Go error, so the harness circuit
// breaker does not trip on legitimate tool refusals. A protocol-level failure
// (non-200 status, JSON-RPC error object, or transport error) is returned as
// an error from this method.
func (c *Client) CallTool(ctx context.Context, name string, args map[string]any) (<-chan ContentBlock, error) {
	logger := log.With().Str("plugin_url", c.baseURL).Str("method", "tools/call").Str("tool", name).Logger()

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

	resp, err := c.call(ctx, req)
	if err != nil {
		return nil, fmt.Errorf("tools/call: %w", err)
	}
	if resp.Error != nil {
		return nil, fmt.Errorf("tools/call error %d: %s", resp.Error.Code, resp.Error.Message)
	}

	var result ToolCallResult
	if err := json.Unmarshal(resp.Result, &result); err != nil {
		return nil, fmt.Errorf("decode tools/call result: %w", err)
	}

	logger.Debug().Int("blocks", len(result.Content)).Bool("is_error", result.IsError).Msg("tools/call completed")

	// Deliver all blocks on a buffered channel and close it. The channel
	// contract (<-chan ContentBlock closed on completion) is preserved so
	// harness.drain and existing callers are unchanged.
	ch := make(chan ContentBlock, capOr(len(result.Content), 16))
	for _, b := range result.Content {
		ch <- b
	}
	close(ch)
	return ch, nil
}

// capOr returns n if it is greater than zero, otherwise fallback.
func capOr(n, fallback int) int {
	if n > 0 {
		return n
	}
	return fallback
}

// ─── helpers ─────────────────────────────────────────────────────────────────

// call performs a standard JSON-RPC HTTP POST (non-streaming).
func (c *Client) call(ctx context.Context, req JSONRPCRequest) (*JSONRPCResponse, error) {
	body, err := json.Marshal(req)
	if err != nil {
		return nil, fmt.Errorf("marshal request: %w", err)
	}

	// Append the method path to the base URL (e.g., /tools/list, /tools/call)
	url := c.baseURL + "/" + req.Method

	httpReq, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(body))
	if err != nil {
		return nil, fmt.Errorf("build request: %w", err)
	}
	httpReq.Header.Set("Content-Type", "application/json")
	httpReq.Header.Set("Accept", "application/json")
	c.applyHeaders(httpReq)

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

// applyHeaders copies the client's configured headers onto the request.
func (c *Client) applyHeaders(req *http.Request) {
	for key, vals := range c.headers {
		for _, v := range vals {
			req.Header.Add(key, v)
		}
	}
}
