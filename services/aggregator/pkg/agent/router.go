// Package agent — AgenticRouter
//
// The AgenticRouter uses an LLM (via OpenRouter) to intelligently select which
// tools to call for a given query. Instead of blindly fanning out to all
// registered tools, the router:
//
//  1. Builds a prompt listing all available tools with their descriptions and
//     parameter schemas.
//  2. Calls OpenRouter's chat completions API to select the most relevant tools.
//  3. Parses the structured JSON response into tool calls.
//  4. Invokes each selected tool through the 9-stage harness.
//  5. Returns the combined results.
//
// This replaces the hardcoded source→tool fan-out in SearchHandler and the
// blind "call all parameterless tools" approach in PollerAgent.
package agent

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"github.com/omni-g/aggregator/pkg/harness"
	"github.com/rs/zerolog/log"
)

// RouterConfig configures the AgenticRouter.
type RouterConfig struct {
	// OpenRouterAPIKey is the API key for OpenRouter.
	OpenRouterAPIKey string
	// OpenRouterModel is the model used for tool selection (e.g. "google/gemini-2.0-flash-001").
	OpenRouterModel string
	// MaxTools caps the number of tools the router can select per query.
	MaxTools int
	// Timeout caps the router LLM call duration.
	Timeout time.Duration
	// Harness is the governance harness all tool calls route through.
	Harness *harness.Harness
	// TenantID is stamped on every invocation.
	TenantID string
}

// DefaultRouterConfig returns sensible defaults.
func DefaultRouterConfig() RouterConfig {
	return RouterConfig{
		OpenRouterModel: "openrouter/free",
		MaxTools:        5,
		Timeout:         30 * time.Second,
	}
}

// ToolCall represents a single tool invocation decided by the router.
type ToolCall struct {
	Name string         `json:"name"`
	Args map[string]any `json:"args"`
}

// RouterResult wraps the results of a routing decision.
type RouterResult struct {
	// Query is the original query that was routed.
	Query string
	// SelectedTools is the list of tools the router selected.
	SelectedTools []string
	// Results is the invoke results, one per selected tool.
	Results []*harness.InvokeResult
	// Errors is any per-tool errors (tool may have been selected but failed).
	Errors []error
}

// AgenticRouter uses an LLM to select which tools to call for a query.
type AgenticRouter struct {
	cfg RouterConfig
}

// NewAgenticRouter creates a router. If apiKey is empty, the router operates
// in fallback mode: it fans out to all available tools (backward compatible).
func NewAgenticRouter(cfg RouterConfig) *AgenticRouter {
	if cfg.MaxTools <= 0 {
		cfg.MaxTools = DefaultRouterConfig().MaxTools
	}
	if cfg.Timeout <= 0 {
		cfg.Timeout = DefaultRouterConfig().Timeout
	}
	if cfg.OpenRouterModel == "" {
		cfg.OpenRouterModel = DefaultRouterConfig().OpenRouterModel
	}
	return &AgenticRouter{cfg: cfg}
}

// Route analyzes the query, selects relevant tools via OpenRouter, invokes
// them through the harness, and returns the combined results.
//
// If OpenRouterAPIKey is empty, falls back to fan-out-all mode.
func (r *AgenticRouter) Route(
	ctx context.Context,
	query string,
	kiqID string,
	searchID string,
) (*RouterResult, error) {
	logger := log.With().Str("query", query).Str("search_id", searchID).Logger()

	// Get available tools from the harness.
	available := r.cfg.Harness.Advertise()
	if len(available) == 0 {
		logger.Warn().Msg("router: no tools available in harness")
		return &RouterResult{Query: query}, nil
	}

	var toolCalls []ToolCall

	if r.cfg.OpenRouterAPIKey == "" {
		// Fallback: fan out to all tools that accept a "query" parameter.
		logger.Info().Msg("router: no OpenRouter API key, using fallback fan-out")
		RouterCallsTotal.WithLabelValues("fallback", "ok").Inc()
		toolCalls = r.fallbackFanOut(query, available)
	} else {
		// Use OpenRouter to intelligently select tools.
		logger.Info().Int("available_tools", len(available)).Msg("router: calling OpenRouter for tool selection")
		start := time.Now()
		var err error
		toolCalls, err = r.selectToolsViaLLM(ctx, query, available)
		RouterLatencySeconds.Observe(time.Since(start).Seconds())
		if err != nil {
			logger.Warn().Err(err).Msg("router: LLM selection failed, falling back to fan-out")
			RouterCallsTotal.WithLabelValues(r.cfg.OpenRouterModel, "error").Inc()
			toolCalls = r.fallbackFanOut(query, available)
		} else {
			RouterCallsTotal.WithLabelValues(r.cfg.OpenRouterModel, "ok").Inc()
		}
	}

	if len(toolCalls) == 0 {
		logger.Info().Msg("router: no tools selected for query")
		return &RouterResult{Query: query}, nil
	}

	// Log the routing decision.
	selectedNames := make([]string, len(toolCalls))
	for i, tc := range toolCalls {
		selectedNames[i] = tc.Name
	}
	logger.Info().Strs("selected_tools", selectedNames).Msg("router: tools selected")
	RouterToolsSelected.Observe(float64(len(toolCalls)))

	// Invoke each selected tool through the harness.
	perm := harness.Permission{TenantID: r.cfg.TenantID}
	result := &RouterResult{
		Query:         query,
		SelectedTools: selectedNames,
	}

	for _, tc := range toolCalls {
		invokeResult, err := r.cfg.Harness.InvokeTool(
			ctx, tc.Name, tc.Args, perm, kiqID, r.cfg.TenantID,
		)
		if err != nil {
			logger.Warn().Str("tool", tc.Name).Err(err).Msg("router: tool invocation failed")
			result.Errors = append(result.Errors, fmt.Errorf("%s: %w", tc.Name, err))
			continue
		}
		result.Results = append(result.Results, invokeResult)
	}

	logger.Info().
		Int("results", len(result.Results)).
		Int("errors", len(result.Errors)).
		Msg("router: routing complete")

	return result, nil
}

// selectToolsViaLLM calls OpenRouter to select the most relevant tools.
func (r *AgenticRouter) selectToolsViaLLM(
	ctx context.Context,
	query string,
	available []harness.ToolDescriptor,
) ([]ToolCall, error) {
	// Build the enriched tool list for the prompt.
	toolList := r.buildToolList(available)

	systemPrompt := fmt.Sprintf(`You are a tool selection router for an intelligence-gathering platform. Given a user query and a list of available tools, select the most relevant tools and construct the arguments for each.

## Query Classification
First, classify the query intent:
- **news**: queries about recent events, "latest", "today", "current", "breaking", "happening now"
- **factual**: "what is", "who is", "tell me about", "explain", "history of", "definition"
- **location**: "weather in", "places near", "restaurants in", "map of", "where is"
- **markets**: "stock", "price", "market", "trading", "shares", "valuation"
- **travel**: "flights", "airport", "route from", "directions"

## Tool Selection Rules
- **news queries** → prefer news_search + news_headlines. Fall back to web_search only if news tools are unavailable.
- **factual queries** → prefer web_search. Optionally add web_fetch for deep reading on a specific URL.
- **location queries** → prefer weather_forecast (for weather) or places_search (for places). Use the location name as the argument.
- **markets queries** → prefer markets_list. Pair with web_search for broader context.
- **travel queries** → prefer flights_overhead or routes.
- **video queries** → prefer video_search.
- **General rule**: Select at most %d tools. Quality over quantity — 1-2 well-chosen tools beat 5 mediocre ones.

## Freshness Awareness
- When the query mentions "today", "latest", "current", "recent" — prefer tools that provide freshness metadata (news_search, news_headlines).
- If results may be stale, the system will add freshness caveats automatically.

## Confidence & Grounding
- Prefer tools that cite sources (web_search, news_search) over tools that return unstructured data.
- For factual claims, prefer web_search which returns source URLs.
- For deep research, pair web_search with web_fetch to get full article text.

## Few-Shot Examples
Query: "latest AI news" → {"tools": [{"name": "news_search", "args": {"query": "latest AI news"}}, {"name": "news_headlines", "args": {"topic": "tech"}}]}
Query: "What is the weather in Tokyo?" → {"tools": [{"name": "weather_forecast", "args": {"location": "Tokyo"}}]}
Query: "Tell me about the history of quantum computing" → {"tools": [{"name": "web_search", "args": {"query": "history of quantum computing"}}]}
Query: "What's happening with Apple stock?" → {"tools": [{"name": "web_search", "args": {"query": "Apple stock price news"}}, {"name": "markets_list", "args": {}}]}
Query: "Find restaurants near Central Park" → {"tools": [{"name": "places_search", "args": {"query": "restaurants near Central Park"}}]}

## Output Format
Return a JSON object with a "tools" array:
{"tools": [{"name": "tool_name", "args": {"param": "value"}}]}

If no tools are relevant, return: {"tools": []}`, r.cfg.MaxTools)

	userPrompt := fmt.Sprintf("Query: %s\n\nAvailable tools:\n%s", query, toolList)

	messages := []openRouterMessage{
		{Role: "system", Content: systemPrompt},
		{Role: "user", Content: userPrompt},
	}
	fmt.Println("Message to openrouter ", messages)
	response, err := callOpenRouter(ctx, r.cfg.OpenRouterAPIKey, r.cfg.OpenRouterModel, messages, r.cfg.Timeout)
	fmt.Println("Recieved response of call open router", response)
	if err != nil {
		return nil, fmt.Errorf("openrouter call: %w", err)
	}

	// Parse the JSON response.
	toolCalls, err := parseToolSelection(response)
	if err != nil {
		return nil, fmt.Errorf("parse tool selection: %w", err)
	}

	// Validate that selected tools actually exist.
	validTools := make(map[string]bool, len(available))
	for _, t := range available {
		validTools[t.Name] = true
	}

	filtered := make([]ToolCall, 0, len(toolCalls))
	for _, tc := range toolCalls {
		if !validTools[tc.Name] {
			log.Warn().Str("tool", tc.Name).Msg("router: LLM selected unknown tool, skipping")
			continue
		}
		filtered = append(filtered, tc)
	}

	return filtered, nil
}

// toolCategory maps tool name prefixes/patterns to category tags and capability hints.
type toolCategory struct {
	tag  string
	hint string
}

// categorizeTool returns a category tag and capability hint for a tool name.
// This enriches the LLM prompt so the router can make smarter selections.
func categorizeTool(name string) toolCategory {
	lower := strings.ToLower(name)
	switch {
	case strings.Contains(lower, "news"):
		return toolCategory{"[news]", "Use for recent news, headlines, and current events. Provides freshness metadata."}
	case strings.Contains(lower, "web_search"):
		return toolCategory{"[web]", "Use for current factual lookups. Returns source URLs. Pair with web_fetch for full articles."}
	case strings.Contains(lower, "web_fetch") || strings.Contains(lower, "web_read"):
		return toolCategory{"[web]", "Use to fetch and read full page content from a URL. Pair with web_search."}
	case strings.Contains(lower, "weather"):
		return toolCategory{"[weather]", "Use for weather forecasts. Requires a location name or lat,long."}
	case strings.Contains(lower, "market"):
		return toolCategory{"[markets]", "Use for stock prices, market data, and financial information."}
	case strings.Contains(lower, "place"):
		return toolCategory{"[places]", "Use for location search, nearby places, and geocoding."}
	case strings.Contains(lower, "flight"):
		return toolCategory{"[travel]", "Use for flight tracking and overhead flights."}
	case strings.Contains(lower, "route"):
		return toolCategory{"[travel]", "Use for directions, transit, and route planning."}
	case strings.Contains(lower, "video"):
		return toolCategory{"[video]", "Use for video search across platforms."}
	case strings.Contains(lower, "image"):
		return toolCategory{"[media]", "Use for image search and generation."}
	case strings.Contains(lower, "email") || strings.Contains(lower, "mail"):
		return toolCategory{"[communication]", "Use for email-related operations."}
	case strings.Contains(lower, "event"):
		return toolCategory{"[events]", "Use for calendar events and scheduling."}
	case strings.Contains(lower, "contact"):
		return toolCategory{"[contacts]", "Use for contact/address book lookups."}
	case strings.Contains(lower, "social"):
		return toolCategory{"[social]", "Use for social media content and feeds."}
	case strings.Contains(lower, "blog"):
		return toolCategory{"[content]", "Use for blog post generation and management."}
	case strings.Contains(lower, "note"):
		return toolCategory{"[notes]", "Use for note-taking and personal knowledge."}
	case strings.Contains(lower, "task"):
		return toolCategory{"[tasks]", "Use for task and todo management."}
	case strings.Contains(lower, "file"):
		return toolCategory{"[files]", "Use for file storage and retrieval."}
	case strings.Contains(lower, "chat"):
		return toolCategory{"[chat]", "Use for conversational AI and chat history."}
	case strings.Contains(lower, "prayer"):
		return toolCategory{"[utility]", "Use for prayer time calculations."}
	case strings.Contains(lower, "stream"):
		return toolCategory{"[media]", "Use for streaming media content."}
	default:
		return toolCategory{"[general]", ""}
	}
}

// buildToolList formats available tools for the LLM prompt with category tags
// and capability hints for smarter tool selection.
func (r *AgenticRouter) buildToolList(tools []harness.ToolDescriptor) string {
	var sb strings.Builder
	for _, t := range tools {
		cat := categorizeTool(t.Name)
		sb.WriteString(fmt.Sprintf("- %s %s: %s", cat.tag, t.Name, t.Description))
		if cat.hint != "" {
			sb.WriteString(" " + cat.hint)
		}
		if len(t.InputSchema) > 0 {
			// Pretty-print the schema compactly.
			var schema map[string]any
			if err := json.Unmarshal(t.InputSchema, &schema); err == nil {
				if props, ok := schema["properties"].(map[string]any); ok {
					sb.WriteString(" (params: ")
					first := true
					for name := range props {
						if !first {
							sb.WriteString(", ")
						}
						sb.WriteString(name)
						first = false
					}
					sb.WriteString(")")
				}
			}
		}
		sb.WriteString("\n")
	}
	return sb.String()
}

// fallbackFanOut uses a lightweight keyword classifier to select relevant tools
// when no OpenRouter API key is configured. This is far better than blind
// fan-out to all 30+ tools.
func (r *AgenticRouter) fallbackFanOut(query string, available []harness.ToolDescriptor) []ToolCall {
	lower := strings.ToLower(query)

	// Classify the query and select appropriate tools.
	var preferredCategories []string

	// News detection.
	if containsAny(lower, "news", "latest", "today", "current", "breaking", "headline", "happening") {
		preferredCategories = append(preferredCategories, "news")
	}
	// Weather detection.
	if containsAny(lower, "weather", "temperature", "forecast", "rain", "snow", "humidity", "climate") {
		preferredCategories = append(preferredCategories, "weather")
	}
	// Location detection.
	if containsAny(lower, "near", "nearby", "restaurant", "hotel", "map", "where is", "direction", "place") {
		preferredCategories = append(preferredCategories, "places")
	}
	// Markets detection.
	if containsAny(lower, "stock", "price", "market", "trading", "share", "nasdaq", "dow", "s&p", "valuation", "crypto", "bitcoin") {
		preferredCategories = append(preferredCategories, "markets")
	}
	// Travel detection.
	if containsAny(lower, "flight", "airport", "route", "transit", "directions") {
		preferredCategories = append(preferredCategories, "travel")
	}
	// Video detection.
	if containsAny(lower, "video", "youtube", "clip", "watch") {
		preferredCategories = append(preferredCategories, "video")
	}

	// Default: web search for factual queries.
	if len(preferredCategories) == 0 {
		preferredCategories = append(preferredCategories, "web")
	}

	// Build a set of preferred categories for O(1) lookup.
	prefSet := make(map[string]bool, len(preferredCategories))
	for _, c := range preferredCategories {
		prefSet[c] = true
	}

	// Select tools matching preferred categories.
	var calls []ToolCall
	for _, t := range available {
		cat := categorizeTool(t.Name)
		catKey := strings.Trim(cat.tag, "[]")
		if prefSet[catKey] && toolAcceptsQueryParam(t) {
			calls = append(calls, ToolCall{
				Name: t.Name,
				Args: map[string]any{"query": query},
			})
		}
	}

	// If no tools matched the preferred categories, fall back to web_search only.
	if len(calls) == 0 {
		for _, t := range available {
			if strings.Contains(strings.ToLower(t.Name), "web_search") && toolAcceptsQueryParam(t) {
				calls = append(calls, ToolCall{
					Name: t.Name,
					Args: map[string]any{"query": query},
				})
				break
			}
		}
	}

	// Cap at MaxTools.
	if len(calls) > r.cfg.MaxTools {
		calls = calls[:r.cfg.MaxTools]
	}

	log.Info().
		Str("query", query).
		Strs("categories", preferredCategories).
		Int("tools_selected", len(calls)).
		Msg("router: fallback classifier selected tools")

	return calls
}

// containsAny returns true if s contains any of the given substrings.
func containsAny(s string, substrs ...string) bool {
	for _, sub := range substrs {
		if strings.Contains(s, sub) {
			return true
		}
	}
	return false
}

// toolAcceptsQueryParam checks if a tool's inputSchema has a "query" property.
func toolAcceptsQueryParam(d harness.ToolDescriptor) bool {
	if len(d.InputSchema) == 0 {
		return false
	}
	var schema struct {
		Properties map[string]any `json:"properties"`
	}
	if err := json.Unmarshal(d.InputSchema, &schema); err != nil {
		return false
	}
	_, ok := schema.Properties["query"]
	return ok
}

// parseToolSelection extracts tool calls from the LLM response JSON.
func parseToolSelection(response string) ([]ToolCall, error) {
	// The LLM might wrap the JSON in markdown code blocks — strip them.
	response = strings.TrimSpace(response)
	response = strings.TrimPrefix(response, "```json")
	response = strings.TrimPrefix(response, "```")
	response = strings.TrimSuffix(response, "```")
	response = strings.TrimSpace(response)

	var result struct {
		Tools []ToolCall `json:"tools"`
	}
	if err := json.Unmarshal([]byte(response), &result); err != nil {
		// Try parsing as a bare array.
		var tools []ToolCall
		if err2 := json.Unmarshal([]byte(response), &tools); err2 != nil {
			return nil, fmt.Errorf("parse response: %w (also tried bare array: %w)", err, err2)
		}
		return tools, nil
	}
	return result.Tools, nil
}
