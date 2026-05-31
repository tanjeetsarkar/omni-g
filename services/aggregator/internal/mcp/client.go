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

	"github.com/rs/zerolog/log"
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
	logger := log.With().Str("plugin_url", c.baseURL).Str("method", "tools/list").Logger()
	logger.Info().Msg("calling MCP tools/list")

	req := JSONRPCRequest{
		JSONRPC: "2.0",
		ID:      1,
		Method:  "tools/list",
	}
	logger.Debug().Interface("request", req).Msg("MCP tools/list request payload")

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
	logger.Info().Int("tool_count", len(result.Tools)).Msg("MCP tools/list completed")
	logger.Debug().Interface("tools", result.Tools).Msg("MCP tools/list response payload")

	return result.Tools, nil
}

// CallTool invokes a named tool with the given arguments and returns a channel
// that receives ContentBlocks streamed over SSE. The channel is closed when the
// stream ends or ctx is cancelled.
func (c *Client) CallTool(ctx context.Context, name string, args map[string]any) (<-chan ContentBlock, error) {
	logger := log.With().Str("plugin_url", c.baseURL).Str("method", "tools/call").Str("tool", name).Logger()
	logger.Info().Msg("calling MCP tool via SSE")
	logger.Debug().Interface("arguments", args).Msg("MCP tools/call arguments payload")

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
	logger.Debug().Str("request", string(body)).Msg("MCP tools/call JSON-RPC request payload")

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
	logger.Info().Int("status_code", httpResp.StatusCode).Msg("MCP SSE connection established")

	if httpResp.StatusCode != http.StatusOK {
		raw, _ := io.ReadAll(io.LimitReader(httpResp.Body, 4096))
		httpResp.Body.Close()
		logger.Debug().Str("error_body", string(raw)).Msg("MCP SSE unexpected response body")
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
		logger.Info().Msg("reading MCP SSE stream")
		parseSSE(ctx, httpResp.Body, ch)
		httpResp.Body.Close() // also close on natural stream end
		logger.Info().Msg("MCP SSE stream closed")
	}()

	return ch, nil
}

// ─── helpers ─────────────────────────────────────────────────────────────────

// call performs a standard JSON-RPC HTTP POST (non-streaming).
func (c *Client) call(ctx context.Context, req JSONRPCRequest) (*JSONRPCResponse, error) {
	logger := log.With().Str("plugin_url", c.baseURL).Str("method", req.Method).Logger()
	body, err := json.Marshal(req)
	if err != nil {
		return nil, fmt.Errorf("marshal request: %w", err)
	}
	logger.Debug().Str("request", string(body)).Msg("MCP JSON-RPC request payload")

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
	logger.Info().Int("status_code", httpResp.StatusCode).Msg("MCP JSON-RPC response received")

	if httpResp.StatusCode != http.StatusOK {
		raw, _ := io.ReadAll(io.LimitReader(httpResp.Body, 4096))
		logger.Debug().Str("error_body", string(raw)).Msg("MCP JSON-RPC unexpected response body")
		return nil, fmt.Errorf("unexpected status %d: %s", httpResp.StatusCode, raw)
	}

	var resp JSONRPCResponse
	if err := json.NewDecoder(httpResp.Body).Decode(&resp); err != nil {
		return nil, fmt.Errorf("decode response: %w", err)
	}
	logger.Debug().Interface("response", resp).Msg("MCP JSON-RPC response payload")

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
		log.Debug().Str("sse_payload", payload).Msg("received MCP SSE payload")
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
