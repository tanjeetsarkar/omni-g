// Package services implements the V4 Micro/Mu-inspired domain services that
// wrap existing MCP plugins and register them as governed tools with the
// Tool Governance Harness.
//
// Each domain service (News, Search, Weather, Feeds, Location) exposes one or
// more tools. The services are thin Go adapters: they translate a governed
// tool invocation into an MCP plugin call and stream the resulting
// ContentBlocks back through the harness. This keeps the harness as the single
// governance boundary while reusing the existing MCP plugin ecosystem.
package services

import (
	"github.com/omni-g/aggregator/pkg/harness"
)

// DomainService is the common interface implemented by each Micro/Mu domain
// service. Register wires the service's tools into the harness.
type DomainService interface {
	// Name returns the service's domain name (e.g. "news", "search").
	Name() string
	// Register registers the service's tools with the harness.
	Register(h *harness.Harness) error
}

// ServiceConfig carries the MCP plugin URLs each service wraps. Empty URLs
// mean the plugin is not configured; the service still registers its tool but
// invocations return a documented "plugin not configured" placeholder block.
type ServiceConfig struct {
	NewsRSSPluginURL   string // newsrss plugin base URL
	ReutersPluginURL   string // reuters plugin base URL
	WikipediaPluginURL string // wikipedia plugin base URL
	WikidataPluginURL  string // wikidata plugin base URL
	// Weather uses the wttr.in HTTP API directly (no MCP plugin).
	// Feeds wraps the newsrss plugin.
}

// All returns the full set of domain services wired with the given config.
func All(cfg ServiceConfig) []DomainService {
	return []DomainService{
		NewNewsService(cfg),
		NewSearchService(cfg),
		NewWeatherService(cfg),
		NewFeedsService(cfg),
	}
}
