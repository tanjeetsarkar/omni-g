package services

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"

	"github.com/omni-g/aggregator/internal/mcp"
	"github.com/omni-g/aggregator/pkg/harness"
)

// mcpPluginTool adapts an MCP plugin (called via mcp.Client) into a
// harness.Tool. It is the shared building block for the News, Search, and
// Feeds services that wrap existing MCP plugins.
type mcpPluginTool struct {
	descriptor harness.ToolDescriptor
	pluginURL  string
	toolName   string // the MCP tool name to call on the plugin
}

// newMCPPluginTool builds a tool that calls toolName on the MCP plugin at
// pluginURL. The harness descriptor uses descName as the governed tool name
// (which may differ from the MCP tool name when a service fans out to
// multiple plugins).
func newMCPPluginTool(descName, descSourceName, descSourceURL, pluginURL, mcpToolName string, risk harness.RiskLevel, schema json.RawMessage) *mcpPluginTool {
	return &mcpPluginTool{
		descriptor: harness.ToolDescriptor{
			Name:        descName,
			Description: fmt.Sprintf("Calls MCP plugin %s tool %s", pluginURL, mcpToolName),
			Version:     "1.0",
			Risk:        risk,
			SourceName:  descSourceName,
			SourceURL:   descSourceURL,
			InputSchema: schema,
		},
		pluginURL: pluginURL,
		toolName:  mcpToolName,
	}
}

func (t *mcpPluginTool) Descriptor() harness.ToolDescriptor { return t.descriptor }

func (t *mcpPluginTool) Invoke(ctx context.Context, args map[string]any) (<-chan mcp.ContentBlock, error) {
	if t.pluginURL == "" {
		// Plugin not configured — return a single documented placeholder block
		// so the harness Normalize stage still produces a valid event with the
		// gap recorded in the payload.
		ch := make(chan mcp.ContentBlock, 1)
		ch <- mcp.ContentBlock{
			Type: mcp.ContentTypeText,
			Text: placeholderJSON(t.descriptor.Name, "MCP plugin not configured"),
		}
		close(ch)
		return ch, nil
	}
	client := mcp.NewClient(t.pluginURL)
	return client.CallTool(ctx, t.toolName, args)
}

// placeholderJSON returns a JSON content-block payload documenting that the
// underlying plugin is not configured. Used by Weather and Location services
// (and any service whose plugin URL is empty).
func placeholderJSON(toolName, reason string) string {
	b, _ := json.Marshal(map[string]any{
		"document_title": toolName,
		"source_name":    toolName,
		"status":         "unavailable",
		"reason":         reason,
		"body":           fmt.Sprintf("Tool %s: %s", toolName, reason),
	})
	return string(b)
}

// fanOutTool calls multiple MCP plugins and merges their ContentBlock streams
// into a single channel. Used by News (newsrss + reuters) and Search
// (wikipedia + wikidata).
type fanOutTool struct {
	descriptor harness.ToolDescriptor
	plugins    []mcpPluginTarget
}

type mcpPluginTarget struct {
	pluginURL string
	toolName  string
}

func newFanOutTool(descName, descSourceName, descSourceURL string, risk harness.RiskLevel, schema json.RawMessage, targets ...mcpPluginTarget) *fanOutTool {
	return &fanOutTool{
		descriptor: harness.ToolDescriptor{
			Name:        descName,
			Description: fmt.Sprintf("Fans out to %d MCP plugins", len(targets)),
			Version:     "1.0",
			Risk:        risk,
			SourceName:  descSourceName,
			SourceURL:   descSourceURL,
			InputSchema: schema,
		},
		plugins: targets,
	}
}

func (t *fanOutTool) Descriptor() harness.ToolDescriptor { return t.descriptor }

func (t *fanOutTool) Invoke(ctx context.Context, args map[string]any) (<-chan mcp.ContentBlock, error) {
	ch := make(chan mcp.ContentBlock, 32)
	go func() {
		defer close(ch)
		emitted := 0
		for _, p := range t.plugins {
			if p.pluginURL == "" {
				ch <- mcp.ContentBlock{
					Type: mcp.ContentTypeText,
					Text: placeholderJSON(t.descriptor.Name, "MCP plugin not configured"),
				}
				emitted++
				continue
			}
			client := mcp.NewClient(p.pluginURL)
			stream, err := client.CallTool(ctx, p.toolName, args)
			if err != nil {
				// Log and continue to the next plugin rather than failing the
				// whole fan-out.
				continue
			}
			for block := range stream {
				select {
				case ch <- block:
					emitted++
				case <-ctx.Done():
					return
				}
			}
		}
		// If no plugin produced any content, emit a placeholder gap block
		// so the harness normalize stage produces a valid event instead of
		// failing with "no content blocks to normalize".
		if emitted == 0 {
			ch <- mcp.ContentBlock{
				Type: mcp.ContentTypeText,
				Text: placeholderJSON(t.descriptor.Name, "all MCP plugins failed or returned no content"),
			}
		}
	}()
	return ch, nil
}

// errPluginNotConfigured is returned when a service has no plugin URL and the
// caller attempts a direct (non-placeholder) invocation.
var errPluginNotConfigured = errors.New("MCP plugin not configured for this service")
