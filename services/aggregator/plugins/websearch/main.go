package main

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"strings"
	"time"

	"github.com/omni-g/aggregator/internal/mcp"
	"github.com/omni-g/aggregator/pkg/harness"
	"github.com/omni-g/aggregator/pkg/plugin"
	"github.com/rs/zerolog/log"
)

const (
	defaultTimeout = 30 * time.Second
	maxResults     = 20
)

func main() {
	// Get configuration from environment
	searxngURL := os.Getenv("SEARXNG_URL")
	if searxngURL == "" {
		log.Fatal().Msg("SEARXNG_URL environment variable is required (e.g., http://searxng:8080)")
	}
	// Ensure URL doesn't have trailing slash
	searxngURL = strings.TrimRight(searxngURL, "/")

	port := 8080
	if p := os.Getenv("PORT"); p != "" {
		fmt.Sscanf(p, "%d", &port)
	}

	// Create plugin server
	server := plugin.NewServer(plugin.ServerConfig{
		Name:        "websearch",
		Version:     "1.0.0",
		Description: "Web search and page fetch via SearXNG + readability",
		Port:        port,
	})

	// HTTP client with timeout
	httpClient := &http.Client{Timeout: defaultTimeout}

	// Register web_search tool
	server.RegisterTool(&plugin.Tool{
		Name:        "web_search",
		Description: "Search the web for current information using SearXNG",
		Version:     "1.0.0",
		Risk:        harness.RiskLow,
		InputSchema: json.RawMessage(`{
			"type": "object",
			"properties": {
				"query": {"type": "string", "description": "Search query"},
				"limit": {"type": "integer", "description": "Max number of results (1-20)", "default": 10, "minimum": 1, "maximum": 20},
				"categories": {"type": "string", "description": "Comma-separated categories (general, news, science, etc.)"},
				"language": {"type": "string", "description": "Language code (en, de, fr, etc.)"},
				"safe_search": {"type": "integer", "description": "Safe search level: 0=off, 1=moderate, 2=strict", "default": 1, "minimum": 0, "maximum": 2}
			},
			"required": ["query"]
		}`),
		Handler: func(ctx context.Context, args map[string]any) (<-chan mcp.ContentBlock, error) {
			query := args["query"].(string)
			limit := 10
			if l, ok := args["limit"].(float64); ok {
				limit = int(l)
			}
			if limit > maxResults {
				limit = maxResults
			}

			categories := ""
			if c, ok := args["categories"].(string); ok {
				categories = c
			}

			language := ""
			if l, ok := args["language"].(string); ok {
				language = l
			}

			safeSearch := 1
			if s, ok := args["safe_search"].(float64); ok {
				safeSearch = int(s)
			}

			results, err := searxngSearch(ctx, httpClient, searxngURL, query, limit, categories, language, safeSearch)
			if err != nil {
				return nil, fmt.Errorf("searxng search failed: %w", err)
			}

			data, _ := json.Marshal(map[string]any{
				"query":   query,
				"results": results,
				"count":   len(results),
				"source":  "searxng",
			})

			ch := make(chan mcp.ContentBlock, 1)
			ch <- mcp.ContentBlock{Type: mcp.ContentTypeText, Text: string(data)}
			close(ch)
			return ch, nil
		},
	})

	// Register web_fetch tool
	server.RegisterTool(&plugin.Tool{
		Name:        "web_fetch",
		Description: "Fetch and extract readable content from a web page URL",
		Version:     "1.0.0",
		Risk:        harness.RiskLow,
		InputSchema: json.RawMessage(`{
			"type": "object",
			"properties": {
				"url": {"type": "string", "description": "URL to fetch and extract content from"},
				"max_length": {"type": "integer", "description": "Maximum content length to return", "default": 10000}
			},
			"required": ["url"]
		}`),
		Handler: func(ctx context.Context, args map[string]any) (<-chan mcp.ContentBlock, error) {
			urlStr := args["url"].(string)
			maxLength := 10000
			if ml, ok := args["max_length"].(float64); ok {
				maxLength = int(ml)
			}

			content, err := fetchAndExtract(ctx, httpClient, urlStr, maxLength)
			if err != nil {
				return nil, fmt.Errorf("fetch failed: %w", err)
			}

			data, _ := json.Marshal(map[string]any{
				"url":     urlStr,
				"title":   content.Title,
				"content": content.Text,
				"source":  "readability",
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

// searxngSearch performs a web search using SearXNG API.
func searxngSearch(ctx context.Context, client *http.Client, baseURL, query string, limit int, categories, language string, safeSearch int) ([]map[string]any, error) {
	params := url.Values{}
	params.Set("q", query)
	params.Set("format", "json")
	params.Set("pageno", "1")
	if limit > 0 {
		params.Set("limit", fmt.Sprintf("%d", limit))
	}
	if categories != "" {
		params.Set("categories", categories)
	}
	if language != "" {
		params.Set("language", language)
	}
	params.Set("safesearch", fmt.Sprintf("%d", safeSearch))

	searchURL := baseURL + "/search?" + params.Encode()

	req, err := http.NewRequestWithContext(ctx, "GET", searchURL, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Accept", "application/json")
	req.Header.Set("User-Agent", "Omni-G-WebSearch/1.0")

	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("searxng search API error: %d - %s", resp.StatusCode, string(body))
	}

	var result struct {
		Results []struct {
			Title         string  `json:"title"`
			URL           string  `json:"url"`
			Content       string  `json:"content"`
			Engine        string  `json:"engine"`
			Score         float64 `json:"score"`
			Category      string  `json:"category"`
			PublishedDate string  `json:"publishedDate"`
		} `json:"results"`
	}

	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return nil, err
	}

	results := make([]map[string]any, 0, len(result.Results))
	for _, r := range result.Results {
		results = append(results, map[string]any{
			"title":     r.Title,
			"url":       r.URL,
			"snippet":   r.Content,
			"engine":    r.Engine,
			"score":     r.Score,
			"category":  r.Category,
			"published": r.PublishedDate,
		})
	}

	return results, nil
}

// fetchAndExtract fetches a URL and extracts readable content using readability.
func fetchAndExtract(ctx context.Context, client *http.Client, urlStr string, maxLength int) (*ExtractedContent, error) {
	req, err := http.NewRequestWithContext(ctx, "GET", urlStr, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("User-Agent", "Omni-G-WebSearch/1.0 (+https://github.com/omni-g/aggregator)")

	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("fetch HTTP error: %d - %s", resp.StatusCode, string(body))
	}

	// Read body with limit
	body, err := io.ReadAll(io.LimitReader(resp.Body, 2*1024*1024)) // 2MB limit
	if err != nil {
		return nil, err
	}

	// Extract title and content using simple HTML parsing
	// In production, consider using a proper readability library like go-readability
	title, content := extractContent(string(body))

	// Truncate if too long
	if len(content) > maxLength {
		content = content[:maxLength] + "... [truncated]"
	}

	return &ExtractedContent{
		Title: title,
		Text:  content,
		URL:   urlStr,
	}, nil
}

// extractContent does basic HTML content extraction.
func extractContent(html string) (title, content string) {
	// Extract title
	titleStart := strings.Index(strings.ToLower(html), "<title>")
	titleEnd := strings.Index(strings.ToLower(html), "</title>")
	if titleStart != -1 && titleEnd != -1 && titleEnd > titleStart {
		title = strings.TrimSpace(html[titleStart+7 : titleEnd])
	}

	// Remove scripts and styles
	html = removeTags(html, "script")
	html = removeTags(html, "style")
	html = removeTags(html, "noscript")

	// Extract text from body or main content
	bodyStart := strings.Index(strings.ToLower(html), "<body")
	if bodyStart != -1 {
		bodyStart = strings.Index(html[bodyStart:], ">")
		if bodyStart != -1 {
			bodyStart += bodyStart + 1
			bodyEnd := strings.Index(strings.ToLower(html[bodyStart:]), "</body>")
			if bodyEnd != -1 {
				html = html[bodyStart : bodyStart+bodyEnd]
			}
		}
	}

	// Strip all HTML tags
	content = stripHTMLTags(html)

	// Clean up whitespace
	content = strings.Join(strings.Fields(content), " ")

	return title, content
}

// removeTags removes all occurrences of a tag and its content.
func removeTags(html, tag string) string {
	lowerHTML := strings.ToLower(html)
	openTag := "<" + tag
	closeTag := "</" + tag + ">"

	for {
		start := strings.Index(lowerHTML, openTag)
		if start == -1 {
			break
		}
		// Find the closing '>' of the opening tag
		tagEnd := strings.Index(html[start:], ">")
		if tagEnd == -1 {
			break
		}
		tagEnd += start + 1

		// Find the closing tag
		closeStart := strings.Index(lowerHTML[tagEnd:], closeTag)
		if closeStart == -1 {
			break
		}
		closeStart += tagEnd
		closeEnd := closeStart + len(closeTag)

		// Remove the tag and its content
		html = html[:start] + html[closeEnd:]
		lowerHTML = strings.ToLower(html)
	}

	return html
}

// stripHTMLTags removes all HTML tags from a string.
func stripHTMLTags(html string) string {
	var result strings.Builder
	inTag := false
	for _, r := range html {
		if r == '<' {
			inTag = true
			continue
		}
		if r == '>' {
			inTag = false
			continue
		}
		if !inTag {
			result.WriteRune(r)
		}
	}
	return result.String()
}

// ExtractedContent holds the extracted page content.
type ExtractedContent struct {
	Title string
	Text  string
	URL   string
}
