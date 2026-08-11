package services

import (
	"github.com/omni-g/aggregator/pkg/harness"
)

// SearchService wraps the wikipedia and wikidata MCP plugins and exposes a
// single governed `web_search` tool that fans out to both.
type SearchService struct {
	cfg ServiceConfig
}

// NewSearchService creates a SearchService from the shared ServiceConfig.
func NewSearchService(cfg ServiceConfig) *SearchService { return &SearchService{cfg: cfg} }

func (s *SearchService) Name() string { return "search" }

// Register registers the web_search tool with the harness.
func (s *SearchService) Register(h *harness.Harness) error {
	schema := []byte(`{
		"type": "object",
		"required": ["query"],
		"properties": {
			"query": {"type": "string", "description": "Web/entity search query"}
		}
	}`)
	tool := newFanOutTool(
		"web_search",
		"Web Search",
		"https://wikipedia.org",
		harness.RiskLow,
		schema,
		mcpPluginTarget{pluginURL: s.cfg.WikipediaPluginURL, toolName: "fetch_wikipedia_article"},
		mcpPluginTarget{pluginURL: s.cfg.WikidataPluginURL, toolName: "fetch_wikidata_facts"},
	)
	return h.Register(tool)
}
