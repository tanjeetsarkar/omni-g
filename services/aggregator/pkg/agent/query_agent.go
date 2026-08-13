package agent

import (
	"context"
	"strings"
	"sync"
	"time"

	"github.com/rs/zerolog/log"
)

// QueryAgentConfig configures a QueryAgent that periodically runs standing
// queries through the AgenticRouter for autonomous, KIQ-driven collection.
type QueryAgentConfig struct {
	// Name is the agent's unique identifier.
	Name string
	// Router is the AgenticRouter used to select and invoke tools per query.
	Router *AgenticRouter
	// Queries is the list of standing queries to run on each cycle.
	Queries []string
	// Interval is the target delay between successive query cycles.
	Interval time.Duration
	// TenantID is stamped on every event.
	TenantID string
	// KIQID is the optional KIQ reference; empty for untasked collection.
	KIQID string
	// OnResult is invoked for every successful InvokeResult from the router.
	OnResult OnResultFunc
}

// QueryAgent periodically runs standing queries through the AgenticRouter.
// Unlike PollerAgent (which blindly calls all parameterless tools), QueryAgent
// uses the router to intelligently select which tools to call for each query.
//
// This is the primary autonomous collection agent for V4 — it replaces the
// PollerAgent's untargeted approach with KIQ-driven, router-mediated collection.
type QueryAgent struct {
	cfg QueryAgentConfig

	mu      sync.Mutex
	health  Health
	cancel  context.CancelFunc
	doneCh  chan struct{}
	started bool
}

// NewQueryAgent creates a QueryAgent. If queries is empty, the agent starts
// but does nothing (no-op).
func NewQueryAgent(cfg QueryAgentConfig) *QueryAgent {
	if cfg.Interval <= 0 {
		cfg.Interval = 5 * time.Minute
	}
	return &QueryAgent{
		cfg: cfg,
		health: Health{
			Status: StatusStopped,
		},
	}
}

// Name returns the agent's identifier.
func (q *QueryAgent) Name() string { return q.cfg.Name }

// Start launches the query loop and blocks until ctx is cancelled or Stop is
// called. It is idempotent.
func (q *QueryAgent) Start(ctx context.Context) error {
	q.mu.Lock()
	if q.started {
		q.mu.Unlock()
		return nil
	}
	q.started = true
	q.health.Status = StatusRunning
	runCtx, cancel := context.WithCancel(ctx)
	q.cancel = cancel
	q.doneCh = make(chan struct{})
	queries := append([]string(nil), q.cfg.Queries...)
	q.mu.Unlock()

	if len(queries) == 0 {
		log.Warn().Str("agent", q.cfg.Name).Msg("query agent has no standing queries, idling")
		<-runCtx.Done()
		return nil
	}

	log.Info().
		Str("agent", q.cfg.Name).
		Int("query_count", len(queries)).
		Dur("interval", q.cfg.Interval).
		Msg("query agent starting")

	// Run immediately on start, then on interval.
	ticker := time.NewTicker(q.cfg.Interval)
	defer ticker.Stop()

	q.runQueries(runCtx, queries) // initial run

	for {
		select {
		case <-runCtx.Done():
			log.Info().Str("agent", q.cfg.Name).Msg("query agent stopped")
			q.mu.Lock()
			q.health.Status = StatusStopped
			q.mu.Unlock()
			return nil
		case <-ticker.C:
			q.runQueries(runCtx, queries)
		}
	}
}

// Stop signals the agent to shut down and waits for in-flight work.
func (q *QueryAgent) Stop(timeout time.Duration) error {
	q.mu.Lock()
	if !q.started {
		q.mu.Unlock()
		return nil
	}
	cancel := q.cancel
	doneCh := q.doneCh
	q.mu.Unlock()
	if cancel != nil {
		cancel()
	}
	if doneCh != nil {
		select {
		case <-doneCh:
		case <-time.After(timeout):
		}
	}
	return nil
}

// Health returns the agent's current runtime state.
func (q *QueryAgent) Health() Health {
	q.mu.Lock()
	defer q.mu.Unlock()
	return q.health
}

// runQueries executes all standing queries through the router.
func (q *QueryAgent) runQueries(ctx context.Context, queries []string) {
	logger := log.With().Str("agent", q.cfg.Name).Int("query_count", len(queries)).Logger()
	logger.Info().Msg("query agent: starting query cycle")

	now := time.Now()
	q.mu.Lock()
	q.health.LastRun = &now
	q.mu.Unlock()

	for _, query := range queries {
		select {
		case <-ctx.Done():
			return
		default:
		}

		queryCtx, cancel := context.WithTimeout(ctx, q.cfg.Router.cfg.Timeout*2) // router + tool calls
		result, err := q.cfg.Router.Route(queryCtx, query, q.cfg.KIQID, "")
		cancel()

		if err != nil {
			logger.Warn().Str("query", query).Err(err).Msg("query agent: route failed")
			q.recordError(err)
			continue
		}

		// Forward results through the OnResult callback.
		if q.cfg.OnResult != nil {
			for _, r := range result.Results {
				if err := q.cfg.OnResult(ctx, r); err != nil {
					logger.Warn().Str("tool", r.Tool.Name).Err(err).Msg("query agent: OnResult error")
				}
			}
		}

		// Record errors from individual tool invocations.
		for _, e := range result.Errors {
			q.recordError(e)
		}

		logger.Info().
			Str("query", query).
			Int("results", len(result.Results)).
			Int("errors", len(result.Errors)).
			Msg("query agent: query complete")
	}

	q.mu.Lock()
	q.health.ErrorCount = 0 // reset on successful cycle
	q.mu.Unlock()
}

func (q *QueryAgent) recordError(err error) {
	q.mu.Lock()
	defer q.mu.Unlock()
	q.health.ErrorCount++
	q.health.LastError = err.Error()
}

// ParseQueries splits a comma-separated query string into a slice.
// Empty strings are filtered out.
func ParseQueries(raw string) []string {
	if raw == "" {
		return nil
	}
	parts := strings.Split(raw, ",")
	result := make([]string, 0, len(parts))
	for _, p := range parts {
		p = strings.TrimSpace(p)
		if p != "" {
			result = append(result, p)
		}
	}
	return result
}
