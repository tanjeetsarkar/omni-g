package agent

import (
	"context"
	"sync"
	"time"

	"github.com/omni-g/aggregator/pkg/harness"
	"github.com/rs/zerolog/log"
)

// WatcherConfig configures a single WatcherAgent.
type WatcherConfig struct {
	// Name is the agent's unique identifier.
	Name string
	// Harness is the governance harness all tool calls route through.
	Harness *harness.Harness
	// ToolName is the streaming tool to watch.
	ToolName string
	// Args are passed to the tool on each (re)connect.
	Args map[string]any
	// TenantID is stamped on every normalized event.
	TenantID string
	// KIQID is the optional KIQ reference; empty for untasked collection.
	KIQID string
	// Permission is the tenant-scoped permission consulted at Stage 5.
	Permission harness.Permission
	// OnResult is invoked for every successful InvokeResult.
	OnResult OnResultFunc
}

// WatcherAgent maintains a long-lived SSE/WebSocket stream with auto-reconnect
// backoff. Unlike PollerAgent (which polls on an interval), WatcherAgent
// holds the stream open and forwards blocks as they arrive. When the stream
// ends or errors, it reconnects with exponential backoff.
//
// All tool calls route through Harness.InvokeTool (the 9-stage lifecycle).
type WatcherAgent struct {
	cfg WatcherConfig

	mu      sync.Mutex
	health  Health
	cancel  context.CancelFunc
	doneCh  chan struct{}
	started bool
}

// NewWatcherAgent creates a WatcherAgent for the given streaming tool.
func NewWatcherAgent(cfg WatcherConfig) *WatcherAgent {
	return &WatcherAgent{
		cfg: cfg,
		health: Health{
			Status: StatusStopped,
		},
	}
}

// Name returns the agent's identifier.
func (w *WatcherAgent) Name() string { return w.cfg.Name }

// Start launches the watch loop and blocks until ctx is cancelled or Stop is
// called. It is idempotent.
func (w *WatcherAgent) Start(ctx context.Context) error {
	w.mu.Lock()
	if w.started {
		w.mu.Unlock()
		return nil
	}
	w.started = true
	w.health.Status = StatusRunning
	runCtx, cancel := context.WithCancel(ctx)
	w.cancel = cancel
	w.doneCh = make(chan struct{})
	w.mu.Unlock()

	log.Info().Str("agent", w.cfg.Name).Str("tool", w.cfg.ToolName).Msg("watcher agent starting")
	w.watch(runCtx)

	w.mu.Lock()
	w.health.Status = StatusStopped
	w.mu.Unlock()
	log.Info().Str("agent", w.cfg.Name).Msg("watcher agent stopped")
	return nil
}

// Stop signals the agent to shut down and waits for in-flight work up to the
// given timeout.
func (w *WatcherAgent) Stop(timeout time.Duration) error {
	w.mu.Lock()
	if !w.started {
		w.mu.Unlock()
		return nil
	}
	cancel := w.cancel
	doneCh := w.doneCh
	w.mu.Unlock()
	if cancel != nil {
		cancel()
	}
	if doneCh != nil {
		select {
		case <-doneCh:
		case <-time.After(timeout):
		}
	}
	w.mu.Lock()
	w.started = false
	w.mu.Unlock()
	return nil
}

// Health returns the agent's current runtime state.
func (w *WatcherAgent) Health() Health {
	w.mu.Lock()
	defer w.mu.Unlock()
	return w.health
}

// watch runs the reconnect loop. Each iteration calls InvokeTool (which opens
// the SSE stream via the tool's Invoke), forwards blocks to OnResult, and
// reconnects with backoff on stream end/error.
func (w *WatcherAgent) watch(ctx context.Context) {
	defer close(w.doneCh)
	logger := log.With().Str("agent", w.cfg.Name).Str("tool", w.cfg.ToolName).Logger()

	attempt := 0
	for {
		if ctx.Err() != nil {
			logger.Info().Msg("watcher context cancelled, stopping")
			return
		}

		result, err := w.cfg.Harness.InvokeTool(ctx, w.cfg.ToolName, w.cfg.Args, w.cfg.Permission, w.cfg.KIQID, w.cfg.TenantID)
		if err != nil {
			// Non-retryable harness rejections.
			msg := err.Error()
			if contains(msg, "circuit breaker open") || contains(msg, "stage permission") || contains(msg, "not registered") {
				logger.Error().Err(err).Msg("watcher stopping: non-retryable harness rejection")
				w.mu.Lock()
				w.health.ErrorCount++
				w.health.LastError = err.Error()
				w.mu.Unlock()
				return
			}
			logger.Warn().Int("attempt", attempt+1).Err(err).Msg("watcher stream failed, reconnecting")
			w.mu.Lock()
			w.health.ErrorCount++
			w.health.LastError = err.Error()
			w.mu.Unlock()
			backoff := backoffDuration(attempt)
			attempt++
			select {
			case <-ctx.Done():
				return
			case <-time.After(backoff):
			}
			continue
		}

		// Stream completed normally — forward the result and reconnect.
		if w.cfg.OnResult != nil {
			if err := w.cfg.OnResult(ctx, result); err != nil {
				logger.Warn().Err(err).Msg("OnResult callback returned error")
			}
		}
		now := time.Now().UTC()
		w.mu.Lock()
		w.health.LastRun = &now
		w.mu.Unlock()
		logger.Debug().Int("blocks", len(result.Blocks)).Msg("stream completed, reconnecting")
		// Reset backoff after a successful cycle.
		attempt = 0
	}
}
