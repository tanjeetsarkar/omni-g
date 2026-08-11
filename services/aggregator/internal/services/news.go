package services

import (
	"github.com/omni-g/aggregator/pkg/harness"
)

// NewsService wraps the newsrss and reuters MCP plugins and exposes a single
// governed `search_news` tool that fans out to both.
type NewsService struct {
	cfg ServiceConfig
}

// NewNewsService creates a NewsService from the shared ServiceConfig.
func NewNewsService(cfg ServiceConfig) *NewsService { return &NewsService{cfg: cfg} }

func (s *NewsService) Name() string { return "news" }

// Register registers the search_news tool with the harness.
func (s *NewsService) Register(h *harness.Harness) error {
	schema := []byte(`{
		"type": "object",
		"properties": {
			"query": {"type": "string", "description": "News search query"}
		}
	}`)
	tool := newFanOutTool(
		"search_news",
		"News RSS",
		"",
		harness.RiskLow,
		schema,
		mcpPluginTarget{pluginURL: s.cfg.NewsRSSPluginURL, toolName: "search_news"},
		mcpPluginTarget{pluginURL: s.cfg.ReutersPluginURL, toolName: "fetch_reuters_rss"},
	)
	return h.Register(tool)
}
