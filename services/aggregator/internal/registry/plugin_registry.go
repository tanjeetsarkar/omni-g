// Package registry implements the plugin registry that discovers and manages plugins.
package registry

import (
	"context"
	"fmt"
	"net/http"
	"os"
	"time"

	"github.com/omni-g/aggregator/internal/mcp"
	"github.com/omni-g/aggregator/pkg/harness"
	"github.com/rs/zerolog/log"
	"gopkg.in/yaml.v3"
)

// PluginConfig represents a single plugin configuration in plugins.yaml.
type PluginConfig struct {
	Name        string            `yaml:"name"`
	Enabled     bool              `yaml:"enabled"`
	Manifest    string            `yaml:"manifest"` // Path to manifest.yaml
	MCPURL      string            `yaml:"mcp_url"`  // MCP server URL (e.g., http://localhost:8081/mcp)
	Headers     map[string]string `yaml:"headers"`  // Per-request headers
	Description string            `yaml:"description"`
}

// PluginsConfig is the top-level structure of plugins.yaml.
type PluginsConfig struct {
	Plugins []PluginConfig `yaml:"plugins"`
}

// PluginRegistry discovers plugins from configured paths and registers their tools with the Harness.
type PluginRegistry struct {
	cfg     PluginsConfig
	harness *harness.Harness
	plugins map[string]*PluginInstance
}

// PluginInstance represents a running plugin with its MCP client.
type PluginInstance struct {
	Config   PluginConfig
	Manifest *PluginManifest
	Client   *mcp.Client
	Tools    []mcp.Tool
}

// NewPluginRegistry creates a PluginRegistry by loading the config file at configPath.
func NewPluginRegistry(configPath string, h *harness.Harness) (*PluginRegistry, error) {
	cfg, err := loadPluginsConfig(configPath)
	if err != nil {
		return nil, fmt.Errorf("plugin registry: %w", err)
	}
	return &PluginRegistry{cfg: cfg, harness: h, plugins: make(map[string]*PluginInstance)}, nil
}

// loadPluginsConfig reads and parses the plugins.yaml config file.
func loadPluginsConfig(path string) (PluginsConfig, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			log.Warn().Str("path", path).Msg("plugin registry: config file not found, no plugins configured")
			return PluginsConfig{}, nil
		}
		return PluginsConfig{}, fmt.Errorf("read config: %w", err)
	}

	// Expand environment variables
	expanded := expandEnvWithDefaults(string(data))

	var cfg PluginsConfig
	if err := yaml.Unmarshal([]byte(expanded), &cfg); err != nil {
		return PluginsConfig{}, fmt.Errorf("parse config: %w", err)
	}

	return cfg, nil
}

// RegisterAll discovers all enabled plugins, connects to their MCP servers,
// and registers their tools with the Harness.
func (r *PluginRegistry) RegisterAll(ctx context.Context) (int, error) {
	total := 0
	for _, pluginCfg := range r.cfg.Plugins {
		if !pluginCfg.Enabled {
			log.Info().Str("plugin", pluginCfg.Name).Msg("plugin registry: plugin disabled, skipping")
			continue
		}

		count, err := r.registerPlugin(ctx, pluginCfg)
		if err != nil {
			log.Error().Str("plugin", pluginCfg.Name).Err(err).Msg("plugin registry: plugin registration failed")
			continue // don't fail the whole registry for one plugin
		}
		total += count
	}
	log.Info().Int("total_tools", total).Msg("plugin registry: all plugins registered")
	return total, nil
}

// registerPlugin connects to a single plugin's MCP server, discovers its tools,
// and registers them with the Harness.
func (r *PluginRegistry) registerPlugin(ctx context.Context, pluginCfg PluginConfig) (int, error) {
	logger := log.With().Str("plugin", pluginCfg.Name).Logger()

	// Load the plugin manifest
	manifest, err := LoadPluginManifest(pluginCfg.Manifest)
	if err != nil {
		return 0, fmt.Errorf("load manifest: %w", err)
	}

	// Resolve MCP URL with env var expansion
	mcpURL := expandEnvWithDefaults(pluginCfg.MCPURL)

	// Build request headers from config, env-expanding each value
	headers := make(http.Header, len(pluginCfg.Headers))
	for k, v := range pluginCfg.Headers {
		expanded := expandEnvWithDefaults(v)
		if expanded != "" {
			headers.Set(k, expanded)
		}
	}

	// Create MCP client
	client := mcp.NewClientWithHeaders(mcpURL, headers)

	// Discover tools with timeout
	discoverCtx, cancel := context.WithTimeout(ctx, 30*time.Second)
	defer cancel()

	tools, err := client.ListTools(discoverCtx)
	if err != nil {
		return 0, fmt.Errorf("discover tools from %s: %w", pluginCfg.Name, err)
	}

	logger.Info().Int("discovered", len(tools)).Msg("plugin registry: tools discovered")

	// Store plugin instance
	instance := &PluginInstance{
		Config:   pluginCfg,
		Manifest: manifest,
		Client:   client,
		Tools:    tools,
	}
	r.plugins[pluginCfg.Name] = instance

	// Register each tool with the Harness
	registered := 0
	for _, tool := range tools {
		// Wrap the MCP tool as a harness.Tool
		ht := newMCPToolFromPlugin(tool, mcpURL, pluginCfg.Name, headers, manifest)
		if err := r.harness.Register(ht); err != nil {
			logger.Warn().Str("tool", tool.Name).Err(err).Msg("plugin registry: failed to register tool")
			continue
		}
		registered++
	}

	logger.Info().Int("registered", registered).Msg("plugin registry: plugin tools registered")
	return registered, nil
}

// GetPlugin returns a plugin instance by name.
func (r *PluginRegistry) GetPlugin(name string) (*PluginInstance, bool) {
	instance, ok := r.plugins[name]
	return instance, ok
}

// ListPlugins returns all registered plugin instances.
func (r *PluginRegistry) ListPlugins() []*PluginInstance {
	result := make([]*PluginInstance, 0, len(r.plugins))
	for _, p := range r.plugins {
		result = append(result, p)
	}
	return result
}

// newMCPToolFromPlugin adapts a discovered MCP tool into a harness.Tool using plugin manifest metadata.
func newMCPToolFromPlugin(tool mcp.Tool, pluginURL, pluginName string, headers http.Header, manifest *PluginManifest) *pluginMCPTool {
	// Derive a human-readable source name from the plugin + tool
	sourceName := fmt.Sprintf("%s/%s", pluginName, tool.Name)

	// Use manifest to create tool descriptor with proper risk level
	descriptor := manifest.ToToolDescriptor(
		tool.Name,
		tool.Description,
		tool.Version,
		tool.InputSchema,
		pluginURL,
	)
	descriptor.SourceName = sourceName

	return &pluginMCPTool{
		descriptor: descriptor,
		pluginURL:  pluginURL,
		toolName:   tool.Name,
		headers:    headers,
	}
}

// pluginMCPTool adapts a discovered MCP tool into a harness.Tool.
type pluginMCPTool struct {
	descriptor harness.ToolDescriptor
	pluginURL  string
	toolName   string
	headers    http.Header
}

func (t *pluginMCPTool) Descriptor() harness.ToolDescriptor { return t.descriptor }

func (t *pluginMCPTool) Invoke(ctx context.Context, args map[string]any) (<-chan mcp.ContentBlock, error) {
	client := mcp.NewClientWithHeaders(t.pluginURL, t.headers)
	return client.CallTool(ctx, t.toolName, args)
}
