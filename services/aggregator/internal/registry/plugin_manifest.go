package registry

// Package registry implements the plugin manifest parsing and validation.

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/omni-g/aggregator/pkg/harness"
	"gopkg.in/yaml.v3"
)

// PluginManifest represents the Omni-G plugin manifest (adapted from OpenClaw SKILL.md).
// It uses YAML frontmatter for metadata declaration.
type PluginManifest struct {
	// Basic identification
	Name        string `yaml:"name"`
	Description string `yaml:"description"`
	Version     string `yaml:"version"`

	// Runtime metadata under metadata.omnig namespace
	Metadata PluginMetadata `yaml:"metadata"`

	// Raw frontmatter for round-tripping
	rawFrontmatter string
}

// PluginMetadata contains Omni-G specific plugin configuration.
type PluginMetadata struct {
	OmniG OmniGMetadata `yaml:"omnig"`
}

// OmniGMetadata holds Omni-G specific plugin requirements and capabilities.
type OmniGMetadata struct {
	// Required environment variables
	RequiresEnv []string `yaml:"requires_env"`

	// Required CLI binaries
	RequiresBins []string `yaml:"requires_bins"`

	// Primary environment variable (for credential validation)
	PrimaryEnv string `yaml:"primary_env"`

	// KIQ tags this plugin can address (for AgenticRouter)
	KIQTags []string `yaml:"kiq_tags"`

	// Whether this plugin enforces tenant isolation
	TenantIsolation bool `yaml:"tenant_isolation"`

	// Risk level for Harness permission checks: low, medium, high
	RiskLevel string `yaml:"risk_level"`

	// Optional: plugin homepage/docs URL
	Homepage string `yaml:"homepage"`

	// Optional: display emoji
	Emoji string `yaml:"emoji"`
}

// LoadPluginManifest reads and parses a plugin manifest from a YAML file.
// The file should have YAML frontmatter (--- ... ---) or be a pure YAML file.
func LoadPluginManifest(path string) (*PluginManifest, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("read manifest %s: %w", path, err)
	}

	content := string(data)
	manifest := &PluginManifest{}

	// Check for YAML frontmatter (--- ... ---)
	if strings.HasPrefix(content, "---") {
		parts := strings.SplitN(content, "---", 3)
		if len(parts) < 3 {
			return nil, fmt.Errorf("invalid frontmatter in %s", path)
		}
		manifest.rawFrontmatter = parts[1]
		content = parts[2]
	}

	// Parse the YAML content
	if err := yaml.Unmarshal([]byte(content), manifest); err != nil {
		return nil, fmt.Errorf("parse manifest %s: %w", path, err)
	}

	// If we had frontmatter, parse that instead (it takes precedence)
	if manifest.rawFrontmatter != "" {
		if err := yaml.Unmarshal([]byte(manifest.rawFrontmatter), manifest); err != nil {
			return nil, fmt.Errorf("parse frontmatter %s: %w", path, err)
		}
	}

	// Validate required fields
	if err := manifest.Validate(); err != nil {
		return nil, fmt.Errorf("validate manifest %s: %w", path, err)
	}

	return manifest, nil
}

// Validate checks that the manifest has all required fields and valid values.
func (m *PluginManifest) Validate() error {
	if strings.TrimSpace(m.Name) == "" {
		return fmt.Errorf("name is required")
	}
	if strings.TrimSpace(m.Description) == "" {
		return fmt.Errorf("description is required")
	}
	if strings.TrimSpace(m.Version) == "" {
		return fmt.Errorf("version is required")
	}

	// Validate risk level
	validRisks := map[string]bool{"low": true, "medium": true, "high": true}
	if m.Metadata.OmniG.RiskLevel != "" && !validRisks[m.Metadata.OmniG.RiskLevel] {
		return fmt.Errorf("risk_level must be low, medium, or high, got %q", m.Metadata.OmniG.RiskLevel)
	}

	// Default risk level to low if not specified
	if m.Metadata.OmniG.RiskLevel == "" {
		m.Metadata.OmniG.RiskLevel = "low"
	}

	return nil
}

// ManifestPath returns the directory containing the manifest file.
func ManifestPath(manifestPath string) string {
	return filepath.Dir(manifestPath)
}

// ToToolDescriptor converts the plugin manifest to a Harness ToolDescriptor.
// This is used when registering the plugin's tools with the Harness.
func (m *PluginManifest) ToToolDescriptor(toolName, toolDescription, toolVersion string, inputSchema []byte, sourceURL string) harness.ToolDescriptor {
	risk := harness.RiskLow
	switch m.Metadata.OmniG.RiskLevel {
	case "medium":
		risk = harness.RiskMedium
	case "high":
		risk = harness.RiskHigh
	}

	return harness.ToolDescriptor{
		Name:        toolName,
		Description: toolDescription,
		Version:     toolVersion,
		Risk:        risk,
		InputSchema: inputSchema,
		SourceName:  m.Name,
		SourceURL:   sourceURL,
	}
}
