package scheduler

import (
	"context"
	"math"
	"sync"
	"time"

	"github.com/omni-g/aggregator/internal/mcp"
	"github.com/omni-g/aggregator/internal/metrics"
	"github.com/rs/zerolog/log"
)

const (
	maxRetries = 5
	maxBackoff = 60 * time.Second
)

// OnBlockFunc is called for every ContentBlock delivered by a plugin tool.
// source is the plugin URL.
type OnBlockFunc func(ctx context.Context, source string, block mcp.ContentBlock) error

// pluginEntry describes a registered MCP plugin server.
type pluginEntry struct {
	url      string
	interval time.Duration
	client   *mcp.Client
}

// Scheduler polls registered MCP plugin servers and delivers ContentBlocks to
// a caller-supplied handler.
type Scheduler struct {
	mu      sync.Mutex
	plugins []pluginEntry
}

// New creates an empty Scheduler.
func New() *Scheduler {
	return &Scheduler{}
}

// RegisterPlugin adds an MCP plugin server to the polling schedule.
// interval is the target delay between successive successful polls.
func (s *Scheduler) RegisterPlugin(url string, interval time.Duration) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.plugins = append(s.plugins, pluginEntry{
		url:      url,
		interval: interval,
		client:   mcp.NewClient(url),
	})
}

// Start launches a polling goroutine for every registered plugin and blocks
// until ctx is cancelled. onBlock is invoked synchronously within each
// goroutine for every ContentBlock received.
//
// It is safe to call RegisterPlugin before Start; calling it after Start has
// no effect on already-running goroutines.
func (s *Scheduler) Start(ctx context.Context, onBlock OnBlockFunc) {
	s.mu.Lock()
	plugins := make([]pluginEntry, len(s.plugins))
	copy(plugins, s.plugins)
	s.mu.Unlock()

	var wg sync.WaitGroup
	for _, p := range plugins {
		wg.Add(1)
		go func(p pluginEntry) {
			defer wg.Done()
			s.runPlugin(ctx, p, onBlock)
		}(p)
	}
	wg.Wait()
}

// ─── internal ────────────────────────────────────────────────────────────────

func (s *Scheduler) runPlugin(ctx context.Context, p pluginEntry, onBlock OnBlockFunc) {
	logger := log.With().Str("plugin", p.url).Logger()

	for {
		if err := s.pollOnce(ctx, p, onBlock); err != nil {
			logger.Error().Err(err).Msg("plugin poll failed")
		}

		select {
		case <-ctx.Done():
			return
		case <-time.After(p.interval):
		}
	}
}

// pollOnce runs a single poll cycle: list tools → call each tool → forward
// blocks. Retries up to maxRetries on transient failures with exponential
// backoff.
func (s *Scheduler) pollOnce(ctx context.Context, p pluginEntry, onBlock OnBlockFunc) error {
	var (
		tools []mcp.Tool
		err   error
	)

	for attempt := 0; attempt < maxRetries; attempt++ {
		tools, err = p.client.ListTools(ctx)
		if err == nil {
			break
		}
		if ctx.Err() != nil {
			return ctx.Err()
		}
		backoff := backoffDuration(attempt)
		log.Warn().Str("plugin", p.url).Int("attempt", attempt+1).
			Dur("backoff", backoff).Err(err).Msg("tools/list failed, retrying")

		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(backoff):
		}
	}

	if err != nil {
		metrics.SchedulerPollTotal.WithLabelValues(p.url, "error").Inc()
		return err
	}

	metrics.SchedulerPollTotal.WithLabelValues(p.url, "ok").Inc()

	for _, tool := range tools {
		if ctx.Err() != nil {
			return ctx.Err()
		}
		if err := s.callTool(ctx, p, tool, onBlock); err != nil {
			log.Warn().Str("plugin", p.url).Str("tool", tool.Name).
				Err(err).Msg("tool call failed")
		}
	}

	return nil
}

func (s *Scheduler) callTool(ctx context.Context, p pluginEntry, tool mcp.Tool, onBlock OnBlockFunc) error {
	ch, err := p.client.CallTool(ctx, tool.Name, nil)
	if err != nil {
		return err
	}

	for block := range ch {
		if err := onBlock(ctx, p.url, block); err != nil {
			log.Warn().Str("plugin", p.url).Str("tool", tool.Name).
				Err(err).Msg("onBlock handler returned error")
		}
	}

	return nil
}

// backoffDuration returns the exponential backoff for the given attempt number,
// capped at maxBackoff.
func backoffDuration(attempt int) time.Duration {
	d := time.Duration(math.Pow(2, float64(attempt))) * 500 * time.Millisecond
	if d > maxBackoff {
		return maxBackoff
	}
	return d
}
