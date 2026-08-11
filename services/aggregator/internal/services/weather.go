package services

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"time"

	"github.com/omni-g/aggregator/internal/mcp"
	"github.com/omni-g/aggregator/pkg/harness"
)

// wttrBaseURL is the wttr.in endpoint. Overridable for tests.
var wttrBaseURL = "https://wttr.in"

// wttrRateLimiter serialises wttr.in calls so the aggregator stays within the
// public service's polite rate limit. wttr.in is a free, community-run
// service; we cap concurrent calls and enforce a minimum interval between
// successive calls to avoid getting blocked.
type wttrRateLimiter struct {
	mu          sync.Mutex
	lastCall    time.Time
	minInterval time.Duration
	sem         chan struct{} // concurrency cap
}

// newWttrRateLimiter builds a limiter allowing at most concurrency concurrent
// calls with at least minInterval between successive acquisitions.
func newWttrRateLimiter(concurrency int, minInterval time.Duration) *wttrRateLimiter {
	if concurrency <= 0 {
		concurrency = 1
	}
	return &wttrRateLimiter{
		minInterval: minInterval,
		sem:         make(chan struct{}, concurrency),
	}
}

// acquire blocks until a call slot is available and the min-interval has
// elapsed since the last call. Release MUST be called when done.
func (r *wttrRateLimiter) acquire(ctx context.Context) error {
	// Concurrency cap.
	select {
	case r.sem <- struct{}{}:
	case <-ctx.Done():
		return ctx.Err()
	}
	// Min-interval gate.
	r.mu.Lock()
	wait := time.Duration(0)
	if !r.lastCall.IsZero() {
		elapsed := time.Since(r.lastCall)
		if elapsed < r.minInterval {
			wait = r.minInterval - elapsed
		}
	}
	r.mu.Unlock()
	if wait > 0 {
		select {
		case <-time.After(wait):
		case <-ctx.Done():
			<-r.sem
			return ctx.Err()
		}
	}
	r.mu.Lock()
	r.lastCall = time.Now()
	r.mu.Unlock()
	return nil
}

func (r *wttrRateLimiter) release() { <-r.sem }

// sharedWttrLimiter is the process-wide rate limiter for wttr.in. wttr.in
// tolerates roughly 1 request per second per IP; we use 2 concurrent calls
// with a 1s min-interval as a polite default.
var sharedWttrLimiter = newWttrRateLimiter(2, 1*time.Second)

// wttrHTTPClient is the HTTP client used for wttr.in calls. Overridable for
// tests.
var wttrHTTPClient = &http.Client{Timeout: 15 * time.Second}

// wttrWeatherTool implements harness.Tool by calling the wttr.in JSON API
// (`?format=j1`) for a given location and returning a single ContentBlock
// carrying the normalized weather payload with human-readable provenance.
type wttrWeatherTool struct {
	descriptor harness.ToolDescriptor
	limiter    *wttrRateLimiter
}

func newWttrWeatherTool() *wttrWeatherTool {
	schema := []byte(`{
		"type": "object",
		"properties": {
			"location": {"type": "string", "description": "Location name or lat,long (e.g. 'Paris' or '48.85,2.35')"}
		}
	}`)
	return &wttrWeatherTool{
		descriptor: harness.ToolDescriptor{
			Name:        "fetch_weather",
			Description: "Fetches current weather from wttr.in (rate-limited).",
			Version:     "1.0",
			Risk:        harness.RiskLow,
			SourceName:  "wttr.in",
			SourceURL:   "https://wttr.in",
			InputSchema: schema,
		},
		limiter: sharedWttrLimiter,
	}
}

func (t *wttrWeatherTool) Descriptor() harness.ToolDescriptor { return t.descriptor }

func (t *wttrWeatherTool) Invoke(ctx context.Context, args map[string]any) (<-chan mcp.ContentBlock, error) {
	location, _ := args["location"].(string)
	// wttr.in returns the caller's IP-derived location when location is empty.

	// Rate-limit the outbound call.
	if err := t.limiter.acquire(ctx); err != nil {
		return nil, fmt.Errorf("wttr rate limiter: %w", err)
	}
	defer t.limiter.release()

	// Build the wttr.in URL: <base>/<location>?format=j1
	u := wttrBaseURL
	if location != "" {
		u += "/" + url.PathEscape(location)
	}
	u += "?format=j1"

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, u, nil)
	if err != nil {
		return nil, fmt.Errorf("build wttr request: %w", err)
	}
	req.Header.Set("Accept", "application/json")
	req.Header.Set("User-Agent", "omni-g-aggregator/1.0 (https://github.com/omni-g)")

	resp, err := wttrHTTPClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("wttr http call: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 512))
		return nil, fmt.Errorf("wttr http %d: %s", resp.StatusCode, strings.TrimSpace(string(body)))
	}

	raw, err := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if err != nil {
		return nil, fmt.Errorf("read wttr response: %w", err)
	}

	// Parse the wttr.in JSON and extract the human-readable fields we care
	// about. We keep the full payload under `raw` for downstream consumers
	// but surface a compact normalized view in the top-level fields so the
	// harness Normalize stage (ingest.ExtractProvenance) can pick up
	// document_title / source_url.
	payload, err := parseWttrJSON(raw, location)
	if err != nil {
		return nil, fmt.Errorf("parse wttr json: %w", err)
	}

	blockText, _ := json.Marshal(payload)
	ch := make(chan mcp.ContentBlock, 1)
	ch <- mcp.ContentBlock{Type: mcp.ContentTypeText, Text: string(blockText)}
	close(ch)
	return ch, nil
}

// wttrResponse is the subset of the wttr.in JSON we decode.
type wttrResponse struct {
	CurrentCondition []struct {
		TempC       string `json:"temp_C"`
		FeelsLikeC  string `json:"FeelsLikeC"`
		Humidity    string `json:"humidity"`
		WindspeedK  string `json:"windspeedKmph"`
		WindDir16   string `json:"winddir16Point"`
		WeatherDesc []struct {
			Value string `json:"value"`
		} `json:"weatherDesc"`
		ObservationTime string `json:"observation_time"`
	} `json:"current_condition"`
	NearestArea []struct {
		AreaName []struct {
			Value string `json:"value"`
		} `json:"areaName"`
		Country []struct {
			Value string `json:"value"`
		} `json:"country"`
		Region []struct {
			Value string `json:"value"`
		} `json:"region"`
		Latitude  string `json:"latitude"`
		Longitude string `json:"longitude"`
	} `json:"nearest_area"`
}

// parseWttrJSON decodes the raw wttr.in response and builds the normalized
// payload block the harness Normalize stage consumes.
func parseWttrJSON(raw []byte, requestedLocation string) (map[string]any, error) {
	var w wttrResponse
	if err := json.Unmarshal(raw, &w); err != nil {
		return nil, err
	}
	if len(w.CurrentCondition) == 0 {
		return nil, fmt.Errorf("wttr response has no current_condition")
	}
	c := w.CurrentCondition[0]
	desc := ""
	if len(c.WeatherDesc) > 0 {
		desc = strings.TrimSpace(c.WeatherDesc[0].Value)
	}
	areaName := requestedLocation
	country := ""
	lat, long := "", ""
	if len(w.NearestArea) > 0 {
		na := w.NearestArea[0]
		if len(na.AreaName) > 0 && na.AreaName[0].Value != "" {
			areaName = strings.TrimSpace(na.AreaName[0].Value)
		}
		if len(na.Country) > 0 {
			country = strings.TrimSpace(na.Country[0].Value)
		}
		lat = na.Latitude
		long = na.Longitude
	}
	title := fmt.Sprintf("Weather: %s — %s, %s°C (feels %s°C)", areaName, desc, c.TempC, c.FeelsLikeC)

	return map[string]any{
		// `text` is required by the Processor schema validator
		// (RawEventEnvelope.validate_payload requires at least one of
		// text/content/data/url). Without it every weather event is
		// dropped at the validation edge.
		"text":             title,
		"document_title":   title,
		"source_name":      "wttr.in",
		"source_url":       "https://wttr.in/" + url.PathEscape(areaName),
		"location":         areaName,
		"country":          country,
		"latitude":         lat,
		"longitude":        long,
		"temp_c":           c.TempC,
		"feels_like_c":     c.FeelsLikeC,
		"humidity":         c.Humidity,
		"wind_speed_kmph":  c.WindspeedK,
		"wind_direction":   c.WindDir16,
		"weather_desc":     desc,
		"observation_time": c.ObservationTime,
		"raw":              json.RawMessage(raw),
	}, nil
}

// WeatherService registers a `fetch_weather` tool backed by the wttr.in JSON
// API with process-wide rate limiting (2 concurrent calls, 1s min-interval).
type WeatherService struct{}

// NewWeatherService creates a WeatherService.
func NewWeatherService(cfg ServiceConfig) *WeatherService { return &WeatherService{} }

func (s *WeatherService) Name() string { return "weather" }

// Register registers the fetch_weather tool with the harness.
func (s *WeatherService) Register(h *harness.Harness) error {
	return h.Register(newWttrWeatherTool())
}
