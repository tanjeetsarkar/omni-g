package services

import (
	"github.com/omni-g/aggregator/pkg/harness"
)

// FeedsService wraps the newsrss MCP plugin (which serves RSS/JSON feeds) and
// exposes a governed `fetch_feed` tool.
type FeedsService struct {
	cfg ServiceConfig
}

// NewFeedsService creates a FeedsService from the shared ServiceConfig.
func NewFeedsService(cfg ServiceConfig) *FeedsService { return &FeedsService{cfg: cfg} }

func (s *FeedsService) Name() string { return "feeds" }

// Register registers the fetch_feed tool with the harness.
func (s *FeedsService) Register(h *harness.Harness) error {
	schema := []byte(`{
		"type": "object",
		"required": ["query"],
		"properties": {
			"query": {"type": "string", "description": "Feed topic or source query"}
		}
	}`)
	tool := newMCPPluginTool(
		"fetch_feed",
		"RSS Feeds",
		"https://newsrss.omni-g.internal",
		s.cfg.NewsRSSPluginURL,
		"search_news",
		harness.RiskLow,
		schema,
	)
	return h.Register(tool)
}
