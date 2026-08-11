package agent

import (
	"context"
	"sync"
	"time"

	"github.com/omni-g/aggregator/internal/mcp"
	"github.com/omni-g/aggregator/pkg/harness"
	"github.com/rs/zerolog/log"
)

// OnResultFunc is called by PollerAgent for every InvokeResult produced by a
// polled tool. The agent has already run the 9-stage harness; the callback is
// responsible for publishing the normalized event via the pipeline. The
// callback receives the harness result and the normalized event envelope.
type OnResultFunc func(ctx context.Context, result *harness.InvokeResult) error

// PollerConfig configures a single PollerAgent.
type PollerConfig struct {
	// Name is the agent's unique identifier.
	Name string
	// Harness is the governance harness all tool calls route through.
	Harness *harness.Harness
	// Interval is the target delay between successive successful poll cycles
	// per tool.
	Interval time.Duration
	// TenantID is stamped on every normalized event (multi-tenant isolation).
	TenantID string
	// KIQID is the optional KIQ reference; empty for untasked collection.
	KIQID string
	// Permission is the tenant-scoped permission consulted at Stage 5.
	Permission harness.Permission
	// OnResult is invoked for every successful InvokeResult.
	OnResult OnResultFunc
}

// PollerAgent executes background interval/cron fetches using tools registered
// in the Harness. It replaces the deprecated internal/scheduler polling loop.
// All tool calls route through Harness.InvokeTool (the 9-stage lifecycle).
type PollerAgent struct {
	cfg PollerConfig

	mu      sync.Mutex
	tools   []string // names of tools to poll
	health  Health
	cancel  context.CancelFunc
	doneCh  chan struct{}
	started bool
}

// NewPollerAgent creates a PollerAgent that polls all advertised tools that do
// not require parameters. Tools with required params are skipped (they must
// be invoked via POST /search with a user-supplied query).
func NewPollerAgent(cfg PollerConfig) *PollerAgent {
	if cfg.Interval <= 0 {
		cfg.Interval = 30 * time.Second
	}
	return &PollerAgent{
		cfg: cfg,
		health: Health{
			Status: StatusStopped,
		},
	}
}

// Name returns the agent's identifier.
func (p *PollerAgent) Name() string { return p.cfg.Name }

// Start launches a polling goroutine per eligible tool and blocks until ctx
// is cancelled or Stop is called. It is idempotent.
func (p *PollerAgent) Start(ctx context.Context) error {
	p.mu.Lock()
	if p.started {
		p.mu.Unlock()
		return nil
	}
	p.started = true
	// Discover eligible tools (no required params) from the harness registry.
	advertised := p.cfg.Harness.Advertise()
	for _, d := range advertised {
		if toolHasRequiredParams(d) {
			log.Info().Str("tool", d.Name).Str("agent", p.cfg.Name).
				Msg("tool has required parameters, skipping scheduled poll")
			continue
		}
		p.tools = append(p.tools, d.Name)
	}
	if len(p.tools) == 0 {
		log.Warn().Str("agent", p.cfg.Name).Msg("poller has no eligible tools to poll")
	}
	p.health.Status = StatusRunning
	runCtx, cancel := context.WithCancel(ctx)
	p.cancel = cancel
	p.doneCh = make(chan struct{})
	tools := append([]string(nil), p.tools...)
	p.mu.Unlock()

	log.Info().Str("agent", p.cfg.Name).Int("tool_count", len(tools)).Dur("interval", p.cfg.Interval).
		Msg("poller agent starting")

	var wg sync.WaitGroup
	for _, toolName := range tools {
		wg.Add(1)
		go func(name string) {
			defer wg.Done()
			p.runTool(runCtx, name)
		}(toolName)
	}
	wg.Wait()
	close(p.doneCh)

	p.mu.Lock()
	p.health.Status = StatusStopped
	p.mu.Unlock()
	log.Info().Str("agent", p.cfg.Name).Msg("poller agent stopped")
	return nil
}

// Stop signals the agent to shut down and waits for in-flight work up to the
// given timeout.
func (p *PollerAgent) Stop(timeout time.Duration) error {
	p.mu.Lock()
	if !p.started {
		p.mu.Unlock()
		return nil
	}
	cancel := p.cancel
	doneCh := p.doneCh
	p.mu.Unlock()
	if cancel != nil {
		cancel()
	}
	if doneCh != nil {
		select {
		case <-doneCh:
		case <-time.After(timeout):
		}
	}
	p.mu.Lock()
	p.started = false
	p.mu.Unlock()
	return nil
}

// Health returns the agent's current runtime state.
func (p *PollerAgent) Health() Health {
	p.mu.Lock()
	defer p.mu.Unlock()
	h := p.health
	return h
}

// runTool polls a single tool on the configured interval with exponential
// backoff on transient failures.
func (p *PollerAgent) runTool(ctx context.Context, toolName string) {
	logger := log.With().Str("agent", p.cfg.Name).Str("tool", toolName).Logger()
	logger.Info().Msg("tool polling loop started")

	for {
		logger.Info().Msg("starting tool poll cycle")
		if err := p.pollOnce(ctx, toolName); err != nil {
			logger.Error().Err(err).Msg("tool poll failed")
			p.mu.Lock()
			p.health.ErrorCount++
			p.health.LastError = err.Error()
			p.mu.Unlock()
		}

		select {
		case <-ctx.Done():
			logger.Info().Msg("tool polling loop stopping")
			return
		case <-time.After(p.cfg.Interval):
		}
	}
}

// pollOnce runs a single poll cycle for one tool through the 9-stage harness.
// Retries up to maxRetries on transient failures with exponential backoff.
func (p *PollerAgent) pollOnce(ctx context.Context, toolName string) error {
	var lastErr error
	for attempt := 0; attempt < maxRetries; attempt++ {
		if ctx.Err() != nil {
			// Context cancelled mid-retry: return the last real error (if any)
			// so the caller sees the tool failure rather than the context error.
			if lastErr != nil {
				return lastErr
			}
			return ctx.Err()
		}
		result, err := p.cfg.Harness.InvokeTool(ctx, toolName, nil, p.cfg.Permission, p.cfg.KIQID, p.cfg.TenantID)
		if err != nil {
			lastErr = err
			// Circuit-breaker-open and permission denials are not retryable.
			msg := err.Error()
			if contains(msg, "circuit breaker open") || contains(msg, "stage permission") {
				return err
			}
			backoff := backoffDuration(attempt)
			log.Warn().Str("tool", toolName).Int("attempt", attempt+1).Dur("backoff", backoff).
				Err(err).Msg("tool poll failed, retrying")
			select {
			case <-ctx.Done():
				// Return the last real error, not the context cancellation.
				if lastErr != nil {
					return lastErr
				}
				return ctx.Err()
			case <-time.After(backoff):
			}
			continue
		}
		// Success: forward to the OnResult callback.
		if p.cfg.OnResult != nil {
			if err := p.cfg.OnResult(ctx, result); err != nil {
				log.Warn().Str("tool", toolName).Err(err).Msg("OnResult callback returned error")
			}
		}
		now := time.Now().UTC()
		p.mu.Lock()
		p.health.LastRun = &now
		p.health.ErrorCount = 0
		p.health.LastError = ""
		p.mu.Unlock()
		return nil
	}
	return lastErr
}

// contains is a tiny strings.Contains helper to avoid importing strings just
// for one call site.
func contains(s, substr string) bool {
	return len(s) >= len(substr) && (s == substr || indexOf(s, substr) >= 0)
}

func indexOf(s, substr string) int {
	for i := 0; i+len(substr) <= len(s); i++ {
		if s[i:i+len(substr)] == substr {
			return i
		}
	}
	return -1
}

// Ensure mcp import is used (ContentBlock type referenced via harness).
var _ = mcp.ContentTypeText
