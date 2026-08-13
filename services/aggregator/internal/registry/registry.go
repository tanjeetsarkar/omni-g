package registry

// Package registry implements a configuration-driven tool registry that
// discovers tools from MCP servers (mu and others) and registers them with
// the Tool Governance Harness.
//
// The registry reads tools.yaml (or a JSON equivalent) at startup, connects
// to each configured MCP server, calls tools/list, and wraps each discovered
// tool as a harness.Tool. Adding a new tool source is a config change — no
// Go code required.

import (
	"context"
	"fmt"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/omni-g/aggregator/internal/mcp"
	"github.com/omni-g/aggregator/pkg/harness"
	"github.com/rs/zerolog/log"
	"gopkg.in/yaml.v3"
)

// RegistryConfig is the top-level structure of tools.yaml.
type RegistryConfig struct {
	MCPServers []MCPServerConfig `yaml:"mcp_servers"`
}

// MCPServerConfig describes a single MCP server to connect to.
type MCPServerConfig struct {
	Name        string            `yaml:"name"`
	URL         string            `yaml:"url"`
	Enabled     bool              `yaml:"enabled"`
	Description string            `yaml:"description"`
	ToolFilter  []string          `yaml:"tool_filter"` // empty = allow all
	Headers     map[string]string `yaml:"headers"`     // per-request headers (e.g. Authorization)
}

// ToolRegistry discovers tools from configured MCP servers and registers them
// with the harness.
type ToolRegistry struct {
	cfg     RegistryConfig
	harness *harness.Harness
}

// New creates a ToolRegistry by loading the config file at configPath.
// If the file doesn't exist or is empty, an empty registry is returned
// (no error — the aggregator can run without external tools).
func New(configPath string, h *harness.Harness) (*ToolRegistry, error) {
	cfg, err := loadConfig(configPath)
	if err != nil {
		return nil, fmt.Errorf("registry: %w", err)
	}
	return &ToolRegistry{cfg: cfg, harness: h}, nil
}

// RegisterAll connects to every enabled MCP server, discovers its tools, and
// registers them with the harness. Returns the total number of tools
// registered.
func (r *ToolRegistry) RegisterAll(ctx context.Context) (int, error) {
	total := 0
	for _, srv := range r.cfg.MCPServers {
		if !srv.Enabled {
			log.Info().Str("server", srv.Name).Msg("registry: server disabled, skipping")
			continue
		}
		count, err := r.registerServer(ctx, srv)
		if err != nil {
			log.Error().Str("server", srv.Name).Err(err).Msg("registry: server registration failed")
			continue // don't fail the whole registry for one server
		}
		total += count
	}
	log.Info().Int("total_tools", total).Msg("registry: all servers registered")
	return total, nil
}

// registerServer connects to a single MCP server, discovers its tools, and
// registers them.
func (r *ToolRegistry) registerServer(ctx context.Context, srv MCPServerConfig) (int, error) {
	logger := log.With().Str("server", srv.Name).Str("url", srv.URL).Logger()

	// Resolve env vars in URL (e.g. "${MU_MCP_URL:-http://...}").
	url := expandEnvWithDefaults(srv.URL)

	// Build request headers from config, env-expanding each value.
	headers := make(http.Header, len(srv.Headers))
	for k, v := range srv.Headers {
		expanded := expandEnvWithDefaults(v)
		if expanded != "" {
			headers.Set(k, expanded)
		}
	}

	client := mcp.NewClientWithHeaders(url, headers)
	discoverCtx, cancel := context.WithTimeout(ctx, 30*time.Second)
	defer cancel()

	tools, err := client.ListTools(discoverCtx)
	if err != nil {
		return 0, fmt.Errorf("discover tools from %s: %w", srv.Name, err)
	}

	logger.Info().Int("discovered", len(tools)).Msg("registry: tools discovered")

	// Build filter set for O(1) lookup.
	filterSet := make(map[string]bool, len(srv.ToolFilter))
	for _, t := range srv.ToolFilter {
		filterSet[t] = true
	}

	registered := 0
	for _, tool := range tools {
		// Apply tool filter if configured.
		if len(filterSet) > 0 && !filterSet[tool.Name] {
			logger.Debug().Str("tool", tool.Name).Msg("registry: tool filtered out")
			continue
		}

		// Wrap the mu tool as a harness.Tool.
		ht := newMCPTool(tool, url, srv.Name, headers)
		if err := r.harness.Register(ht); err != nil {
			logger.Warn().Str("tool", tool.Name).Err(err).Msg("registry: failed to register tool")
			continue
		}
		registered++
	}

	logger.Info().Int("registered", registered).Msg("registry: server tools registered")
	return registered, nil
}

// loadConfig reads and parses the YAML config file. Returns an empty config
// if the file doesn't exist.
func loadConfig(path string) (RegistryConfig, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			log.Warn().Str("path", path).Msg("registry: config file not found, no external tools configured")
			return RegistryConfig{}, nil
		}
		return RegistryConfig{}, fmt.Errorf("read config: %w", err)
	}

	// Expand env vars in the raw YAML before parsing.
	expanded := expandEnvWithDefaults(string(data))

	var cfg RegistryConfig
	if err := yaml.Unmarshal([]byte(expanded), &cfg); err != nil {
		return RegistryConfig{}, fmt.Errorf("parse config: %w", err)
	}

	return cfg, nil
}

// expandEnvWithDefaults expands environment variable references in s,
// supporting $VAR, ${VAR}, and shell-style ${VAR:-default} syntax.
//
// os.ExpandEnv does NOT understand ${VAR:-default}: it treats the whole
// "VAR:-default" as a single variable name, looks it up, finds nothing, and
// substitutes an empty string. tools.yaml uses the ${VAR:-default} form for
// self-documenting defaults, so a naive os.ExpandEnv silently turns
// `url: "${MU_MCP_URL:-http://...}"` into an empty URL and
// `enabled: ${MU_ENABLED:-true}` into an empty (false) bool — which disables
// every MCP server and leaves the harness empty. This helper parses the
// `:-default` form so the default is used when the variable is unset or empty.
func expandEnvWithDefaults(s string) string {
	var buf strings.Builder
	i := 0
	for i < len(s) {
		if s[i] == '$' && i+1 < len(s) {
			switch {
			case s[i+1] == '{':
				// ${VAR} or ${VAR:-default}
				end := strings.IndexByte(s[i+2:], '}')
				if end < 0 {
					// Unterminated reference — copy the '$' and move on.
					buf.WriteByte(s[i])
					i++
					continue
				}
				inner := s[i+2 : i+2+end]
				name, def, hasDefault := splitEnvDefault(inner)
				if val, ok := os.LookupEnv(name); ok && val != "" {
					buf.WriteString(val)
				} else if hasDefault {
					buf.WriteString(def)
				}
				i += 2 + end + 1 // skip "${...}"
			case isEnvNameChar(s[i+1]):
				// $VAR
				j := i + 1
				for j < len(s) && isEnvNameChar(s[j]) {
					j++
				}
				if val, ok := os.LookupEnv(s[i+1 : j]); ok {
					buf.WriteString(val)
				}
				i = j
			default:
				buf.WriteByte(s[i])
				i++
			}
			continue
		}
		buf.WriteByte(s[i])
		i++
	}
	return buf.String()
}

// splitEnvDefault splits an env reference body on the first ":-" into a
// variable name and its default. hasDefault is true only when ":-" is present.
func splitEnvDefault(inner string) (name, def string, hasDefault bool) {
	if idx := strings.Index(inner, ":-"); idx >= 0 {
		return inner[:idx], inner[idx+2:], true
	}
	return inner, "", false
}

// isEnvNameChar reports whether c is a valid character in an environment
// variable name (alphanumeric or underscore).
func isEnvNameChar(c byte) bool {
	return c == '_' || (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9')
}

// mcpTool adapts a discovered MCP tool into a harness.Tool.
type mcpTool struct {
	descriptor harness.ToolDescriptor
	pluginURL  string
	toolName   string
	headers    http.Header
}

func newMCPTool(tool mcp.Tool, pluginURL, serverName string, headers http.Header) *mcpTool {
	// Derive a human-readable source name from the server + tool.
	sourceName := fmt.Sprintf("%s/%s", serverName, tool.Name)

	return &mcpTool{
		descriptor: harness.ToolDescriptor{
			Name:        tool.Name,
			Description: tool.Description,
			Version:     tool.Version,
			Risk:        harness.RiskLow, // mu tools are read-only by default
			InputSchema: tool.InputSchema,
			SourceName:  sourceName,
			SourceURL:   pluginURL,
		},
		pluginURL: pluginURL,
		toolName:  tool.Name,
		headers:   headers,
	}
}

func (t *mcpTool) Descriptor() harness.ToolDescriptor { return t.descriptor }

func (t *mcpTool) Invoke(ctx context.Context, args map[string]any) (<-chan mcp.ContentBlock, error) {
	client := mcp.NewClientWithHeaders(t.pluginURL, t.headers)
	return client.CallTool(ctx, t.toolName, args)
}

// Ensure yaml import is used (handled by go mod tidy).
var _ = strings.TrimSpace // keep strings import
