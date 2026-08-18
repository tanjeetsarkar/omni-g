package main

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/mmcdole/gofeed"
	"github.com/omni-g/aggregator/internal/mcp"
	"github.com/omni-g/aggregator/pkg/harness"
	"github.com/omni-g/aggregator/pkg/plugin"
	"github.com/rs/zerolog/log"
)

const (
	defaultTimeout   = 30 * time.Second
	defaultFeedLimit = 50
	defaultItemLimit = 30
	refreshInterval  = 15 * time.Minute
	maxContentLength = 10000
)

var (
	// Default RSS feeds for news aggregation
	defaultFeeds = []string{
		"https://feeds.bbci.co.uk/news/rss.xml",
		"https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml",
		"https://feeds.reuters.com/reuters/topNews",
		"https://www.theguardian.com/world/rss",
		"https://feeds.arstechnica.com/arstechnica/technology-lab",
		"https://techcrunch.com/feed/",
		"https://www.wired.com/feed/rss",
		"https://feeds.feedburner.com/venturebeat/SZYF",
		"https://www.engadget.com/rss.xml",
		"https://www.theverge.com/rss/index.xml",
	}
)

type FeedItem struct {
	ID          string    `json:"id"`
	Title       string    `json:"title"`
	URL         string    `json:"url"`
	Description string    `json:"description,omitempty"`
	Content     string    `json:"content,omitempty"`
	Published   time.Time `json:"published"`
	Category    string    `json:"category,omitempty"`
	Source      string    `json:"source"`
	Image       string    `json:"image,omitempty"`
}

type FeedCache struct {
	mu       sync.RWMutex
	items    []FeedItem
	byID     map[string]FeedItem
	lastSync time.Time
}

func main() {
	port := 8080
	if p := os.Getenv("PORT"); p != "" {
		fmt.Sscanf(p, "%d", &port)
	}

	// Create plugin server
	server := plugin.NewServer(plugin.ServerConfig{
		Name:        "newsearch",
		Version:     "1.0.0",
		Description: "News headlines, article read, and news search via RSS aggregation",
		Port:        port,
	})

	// Initialize feed cache
	cache := &FeedCache{
		items: make([]FeedItem, 0),
		byID:  make(map[string]FeedItem),
	}

	// HTTP client for fetching feeds and articles
	httpClient := &http.Client{Timeout: defaultTimeout}

	// Start background feed refresher
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go cache.refreshLoop(ctx, httpClient)

	// Initial sync
	cache.syncFeeds(ctx, httpClient)

	// Register news_headlines tool
	server.RegisterTool(&plugin.Tool{
		Name:        "news_headlines",
		Description: "Get recent news headlines with optional topic filter",
		Version:     "1.0.0",
		Risk:        harness.RiskLow,
		InputSchema: json.RawMessage(`{
			"type": "object",
			"properties": {
				"topic": {"type": "string", "description": "Optional topic/category filter (e.g., tech, world, business, science)"},
				"limit": {"type": "integer", "description": "Max number of headlines (default 30)", "default": 30, "minimum": 1, "maximum": 100},
				"hours": {"type": "integer", "description": "Only show articles from last N hours", "default": 24}
			}
		}`),
		Handler: func(ctx context.Context, args map[string]any) (<-chan mcp.ContentBlock, error) {
			topic := ""
			if t, ok := args["topic"].(string); ok {
				topic = strings.ToLower(t)
			}
			limit := defaultItemLimit
			if l, ok := args["limit"].(float64); ok {
				limit = int(l)
			}
			hours := 24
			if h, ok := args["hours"].(float64); ok {
				hours = int(h)
			}

			items := cache.getHeadlines(topic, limit, hours)

			data, _ := json.Marshal(map[string]any{
				"topic":  topic,
				"items":  items,
				"count":  len(items),
				"source": "rss_aggregation",
				"fresh":  time.Since(cache.lastSync).String(),
			})

			ch := make(chan mcp.ContentBlock, 1)
			ch <- mcp.ContentBlock{Type: mcp.ContentTypeText, Text: string(data)}
			close(ch)
			return ch, nil
		},
	})

	// Register news_read tool
	server.RegisterTool(&plugin.Tool{
		Name:        "news_read",
		Description: "Read a full news article by ID or URL",
		Version:     "1.0.0",
		Risk:        harness.RiskLow,
		InputSchema: json.RawMessage(`{
			"type": "object",
			"properties": {
				"id": {"type": "string", "description": "Article ID from headlines or article URL"}
			},
			"required": ["id"]
		}`),
		Handler: func(ctx context.Context, args map[string]any) (<-chan mcp.ContentBlock, error) {
			id := args["id"].(string)

			item, err := cache.getArticle(ctx, httpClient, id)
			if err != nil {
				return nil, fmt.Errorf("article not found: %w", err)
			}

			data, _ := json.Marshal(map[string]any{
				"id":          item.ID,
				"title":       item.Title,
				"url":         item.URL,
				"description": item.Description,
				"content":     item.Content,
				"published":   item.Published.Format(time.RFC3339),
				"category":    item.Category,
				"source":      item.Source,
				"image":       item.Image,
			})

			ch := make(chan mcp.ContentBlock, 1)
			ch <- mcp.ContentBlock{Type: mcp.ContentTypeText, Text: string(data)}
			close(ch)
			return ch, nil
		},
	})

	// Register news_search tool
	server.RegisterTool(&plugin.Tool{
		Name:        "news_search",
		Description: "Search news articles by query across aggregated feeds",
		Version:     "1.0.0",
		Risk:        harness.RiskLow,
		InputSchema: json.RawMessage(`{
			"type": "object",
			"properties": {
				"query": {"type": "string", "description": "Search terms (e.g., 'latest AI news', 'climate change')"},
				"limit": {"type": "integer", "description": "Max results (default 20)", "default": 20, "minimum": 1, "maximum": 50},
				"hours": {"type": "integer", "description": "Only search articles from last N hours", "default": 72}
			},
			"required": ["query"]
		}`),
		Handler: func(ctx context.Context, args map[string]any) (<-chan mcp.ContentBlock, error) {
			query := strings.ToLower(args["query"].(string))
			limit := 20
			if l, ok := args["limit"].(float64); ok {
				limit = int(l)
			}
			hours := 72
			if h, ok := args["hours"].(float64); ok {
				hours = int(h)
			}

			items := cache.searchArticles(query, limit, hours)

			data, _ := json.Marshal(map[string]any{
				"query":   query,
				"results": items,
				"count":   len(items),
				"source":  "rss_aggregation",
				"fresh":   time.Since(cache.lastSync).String(),
			})

			ch := make(chan mcp.ContentBlock, 1)
			ch <- mcp.ContentBlock{Type: mcp.ContentTypeText, Text: string(data)}
			close(ch)
			return ch, nil
		},
	})

	// Run the server (blocks until SIGINT/SIGTERM)
	if err := server.Run(); err != nil {
		log.Error().Err(err).Msg("Server error")
		os.Exit(1)
	}
}

// refreshLoop periodically refreshes the feed cache.
func (c *FeedCache) refreshLoop(ctx context.Context, client *http.Client) {
	ticker := time.NewTicker(refreshInterval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			c.syncFeeds(ctx, client)
		}
	}
}

// syncFeeds fetches all configured feeds and updates the cache.
func (c *FeedCache) syncFeeds(ctx context.Context, client *http.Client) {
	feeds := getConfiguredFeeds()
	var allItems []FeedItem
	var mu sync.Mutex
	var wg sync.WaitGroup

	for _, feedURL := range feeds {
		wg.Add(1)
		go func(url string) {
			defer wg.Done()
			items := c.fetchFeed(ctx, client, url)
			mu.Lock()
			allItems = append(allItems, items...)
			mu.Unlock()
		}(feedURL)
	}

	wg.Wait()

	// Sort by publication date (newest first)
	sort.Slice(allItems, func(i, j int) bool {
		return allItems[i].Published.After(allItems[j].Published)
	})

	// Deduplicate by URL
	seen := make(map[string]bool)
	uniqueItems := make([]FeedItem, 0, len(allItems))
	for _, item := range allItems {
		if !seen[item.URL] {
			seen[item.URL] = true
			uniqueItems = append(uniqueItems, item)
		}
	}

	// Update cache
	c.mu.Lock()
	c.items = uniqueItems
	c.byID = make(map[string]FeedItem, len(uniqueItems))
	for _, item := range uniqueItems {
		c.byID[item.ID] = item
	}
	c.lastSync = time.Now()
	c.mu.Unlock()

	log.Info().Int("total_items", len(uniqueItems)).Int("feeds", len(feeds)).Msg("newsearch: feed cache updated")
}

// fetchFeed fetches and parses a single RSS feed.
func (c *FeedCache) fetchFeed(ctx context.Context, client *http.Client, feedURL string) []FeedItem {
	req, err := http.NewRequestWithContext(ctx, "GET", feedURL, nil)
	if err != nil {
		log.Warn().Str("feed", feedURL).Err(err).Msg("newsearch: failed to create request")
		return nil
	}
	req.Header.Set("User-Agent", "Omni-G NewSearch/1.0")

	resp, err := client.Do(req)
	if err != nil {
		log.Warn().Str("feed", feedURL).Err(err).Msg("newsearch: failed to fetch feed")
		return nil
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		log.Warn().Str("feed", feedURL).Int("status", resp.StatusCode).Msg("newsearch: feed returned non-200")
		return nil
	}

	parser := gofeed.NewParser()
	feed, err := parser.Parse(resp.Body)
	if err != nil {
		log.Warn().Str("feed", feedURL).Err(err).Msg("newsearch: failed to parse feed")
		return nil
	}

	sourceName := feed.Title
	if sourceName == "" {
		sourceName = feedURL
	}

	var items []FeedItem
	for _, entry := range feed.Items {
		if len(items) >= defaultFeedLimit {
			break
		}

		published := time.Now()
		if entry.PublishedParsed != nil {
			published = *entry.PublishedParsed
		} else if entry.UpdatedParsed != nil {
			published = *entry.UpdatedParsed
		}

		// Generate ID from URL hash
		hashInput := entry.Link + entry.Title
		id := fmt.Sprintf("%x", len(hashInput))
		if len(id) < 12 {
			id = id + strings.Repeat("0", 12-len(id))
		}
		id = id[:12]

		// Extract image
		image := ""
		if entry.Image != nil && entry.Image.URL != "" {
			image = entry.Image.URL
		} else if len(entry.Enclosures) > 0 {
			for _, enc := range entry.Enclosures {
				if strings.HasPrefix(enc.Type, "image/") {
					image = enc.URL
					break
				}
			}
		}

		// Category from feed categories or entry categories
		category := ""
		if len(entry.Categories) > 0 {
			category = strings.ToLower(entry.Categories[0])
		}

		items = append(items, FeedItem{
			ID:          id,
			Title:       entry.Title,
			URL:         entry.Link,
			Description: entry.Description,
			Content:     entry.Content,
			Published:   published,
			Category:    category,
			Source:      sourceName,
			Image:       image,
		})
	}

	return items
}

// getHeadlines returns filtered headlines from cache.
func (c *FeedCache) getHeadlines(topic string, limit, hours int) []FeedItem {
	c.mu.RLock()
	defer c.mu.RUnlock()

	cutoff := time.Now().Add(-time.Duration(hours) * time.Hour)
	var result []FeedItem

	for _, item := range c.items {
		if len(result) >= limit {
			break
		}
		if item.Published.Before(cutoff) {
			continue
		}
		if topic != "" && !strings.Contains(strings.ToLower(item.Category), topic) &&
			!strings.Contains(strings.ToLower(item.Title), topic) &&
			!strings.Contains(strings.ToLower(item.Source), topic) {
			continue
		}
		result = append(result, item)
	}

	return result
}

// getArticle retrieves a full article by ID or URL.
func (c *FeedCache) getArticle(ctx context.Context, client *http.Client, id string) (*FeedItem, error) {
	c.mu.RLock()
	item, ok := c.byID[id]
	c.mu.RUnlock()

	if ok {
		// Try to fetch full content if not already present
		if item.Content == "" && item.URL != "" {
			content, err := fetchArticleContent(ctx, client, item.URL)
			if err == nil {
				item.Content = content
			}
		}
		return &item, nil
	}

	// If not found by ID, try as URL
	if strings.HasPrefix(id, "http://") || strings.HasPrefix(id, "https://") {
		content, err := fetchArticleContent(ctx, client, id)
		if err != nil {
			return nil, err
		}
		return &FeedItem{
			ID:      fmt.Sprintf("%x", len(id))[:12],
			URL:     id,
			Content: content,
			Source:  "direct_fetch",
		}, nil
	}

	return nil, fmt.Errorf("article not found: %s", id)
}

// searchArticles searches cached articles by query.
func (c *FeedCache) searchArticles(query string, limit, hours int) []FeedItem {
	c.mu.RLock()
	defer c.mu.RUnlock()

	cutoff := time.Now().Add(-time.Duration(hours) * time.Hour)
	queryTerms := strings.Fields(query)
	var result []FeedItem

	for _, item := range c.items {
		if len(result) >= limit {
			break
		}
		if item.Published.Before(cutoff) {
			continue
		}

		// Simple text search in title, description, content
		haystack := strings.ToLower(item.Title + " " + item.Description + " " + item.Content)
		match := true
		for _, term := range queryTerms {
			if !strings.Contains(haystack, term) {
				match = false
				break
			}
		}
		if match {
			result = append(result, item)
		}
	}

	return result
}

// fetchArticleContent fetches and extracts readable content from an article URL.
func fetchArticleContent(ctx context.Context, client *http.Client, url string) (string, error) {
	req, err := http.NewRequestWithContext(ctx, "GET", url, nil)
	if err != nil {
		return "", err
	}
	req.Header.Set("User-Agent", "Omni-G NewSearch/1.0")

	resp, err := client.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("HTTP %d", resp.StatusCode)
	}

	// Read body (limit size)
	body, err := io.ReadAll(io.LimitReader(resp.Body, 500000))
	if err != nil {
		return "", err
	}

	// Simple extraction - in production, use readability library
	content := string(body)
	// Strip scripts, styles, etc. (basic)
	content = stripHTMLTags(content)

	// Truncate
	if len(content) > maxContentLength {
		content = content[:maxContentLength] + "... [truncated]"
	}

	return content, nil
}

// stripHTMLTags does basic HTML tag removal.
func stripHTMLTags(html string) string {
	// Very basic tag stripping - replace with proper readability in production
	result := strings.ReplaceAll(html, "<script", "<!--script")
	result = strings.ReplaceAll(result, "</script>", "/script-->")
	result = strings.ReplaceAll(result, "<style", "<!--style")
	result = strings.ReplaceAll(result, "</style>", "/style-->")

	// Remove all tags
	inTag := false
	var builder strings.Builder
	for _, r := range result {
		if r == '<' {
			inTag = true
			continue
		}
		if r == '>' {
			inTag = false
			continue
		}
		if !inTag {
			builder.WriteRune(r)
		}
	}

	// Clean up whitespace
	text := builder.String()
	text = strings.ReplaceAll(text, "\n", " ")
	text = strings.ReplaceAll(text, "\t", " ")
	for strings.Contains(text, "  ") {
		text = strings.ReplaceAll(text, "  ", " ")
	}

	return strings.TrimSpace(text)
}

// getConfiguredFeeds returns the list of RSS feeds to aggregate.
func getConfiguredFeeds() []string {
	// In production, read from config file or environment
	feedsEnv := os.Getenv("NEWS_FEEDS")
	if feedsEnv != "" {
		return strings.Split(feedsEnv, ",")
	}
	return defaultFeeds
}
