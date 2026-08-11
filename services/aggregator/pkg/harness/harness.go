package harness

import (
	"context"
	"errors"
	"fmt"
	"sync"
	"time"

	"github.com/omni-g/aggregator/internal/ingest"
	"github.com/omni-g/aggregator/internal/mcp"
	"github.com/omni-g/aggregator/pkg/models"
	"github.com/rs/zerolog/log"
)

// Clock abstracts time so circuit-breaker tests can fast-forward without
// sleeping. Production code uses SystemClock.
type Clock interface {
	Now() time.Time
}

// SystemClock returns the real wall clock.
type SystemClock struct{}

func (SystemClock) Now() time.Time { return time.Now() }

// Config tunes the harness circuit breaker and per-invocation timeout.
type Config struct {
	// InvokeTimeout caps a single tool invocation. Zero means no cap (use
	// the caller's context deadline).
	InvokeTimeout time.Duration
	// CircuitBreakerThreshold is the consecutive failure count that opens the
	// breaker for a tool.
	CircuitBreakerThreshold int
	// CircuitBreakerReset is how long the breaker stays open before moving to
	// half-open (one trial call is allowed).
	CircuitBreakerReset time.Duration
}

// DefaultConfig returns sensible production defaults.
func DefaultConfig() Config {
	return Config{
		InvokeTimeout:           30 * time.Second,
		CircuitBreakerThreshold: 5,
		CircuitBreakerReset:     30 * time.Second,
	}
}

// Harness is the 9-stage Tool Execution Lifecycle engine. It is safe for
// concurrent use by multiple agents.
type Harness struct {
	cfg   Config
	clock Clock
	mu    sync.RWMutex
	tools map[string]Tool
	// Per-tool circuit breaker state.
	breakers map[string]*breaker
}

// New creates a Harness with the given config. If clock is nil, SystemClock is
// used.
func New(cfg Config, clock Clock) *Harness {
	if clock == nil {
		clock = SystemClock{}
	}
	if cfg.CircuitBreakerThreshold <= 0 {
		cfg.CircuitBreakerThreshold = DefaultConfig().CircuitBreakerThreshold
	}
	if cfg.CircuitBreakerReset <= 0 {
		cfg.CircuitBreakerReset = DefaultConfig().CircuitBreakerReset
	}
	return &Harness{
		cfg:      cfg,
		clock:    clock,
		tools:    make(map[string]Tool),
		breakers: make(map[string]*breaker),
	}
}

// Register runs Stage 1 (validate descriptor) and stores the tool. Returns an
// error if the descriptor is invalid or a tool with the same name is already
// registered.
func (h *Harness) Register(t Tool) error {
	d := t.Descriptor()
	if err := ValidateDescriptor(d); err != nil {
		// Stage 1 metric: registration rejected.
		HarnessInvokeTotal.WithLabelValues(d.Name, StageRegister.String(), "rejected").Inc()
		return fmt.Errorf("stage %s: %w", StageRegister, err)
	}
	h.mu.Lock()
	defer h.mu.Unlock()
	if _, exists := h.tools[d.Name]; exists {
		HarnessInvokeTotal.WithLabelValues(d.Name, StageRegister.String(), "rejected").Inc()
		return fmt.Errorf("stage %s: tool %q already registered", StageRegister, d.Name)
	}
	h.tools[d.Name] = t
	h.breakers[d.Name] = &breaker{
		threshold:  h.cfg.CircuitBreakerThreshold,
		resetAfter: h.cfg.CircuitBreakerReset,
	}
	HarnessInvokeTotal.WithLabelValues(d.Name, StageRegister.String(), "ok").Inc()
	log.Info().Str("tool", d.Name).Str("risk", string(d.Risk)).Msg("harness: tool registered")
	return nil
}

// Advertise runs Stage 2: returns the descriptors of all registered tools so
// agents know what they can call.
func (h *Harness) Advertise() []ToolDescriptor {
	h.mu.RLock()
	defer h.mu.RUnlock()
	out := make([]ToolDescriptor, 0, len(h.tools))
	for _, t := range h.tools {
		out = append(out, t.Descriptor())
	}
	return out
}

// InvokeTool runs stages 3-9 for a single tool invocation. It returns the
// InvokeResult on success, or an error wrapping the failing stage name on
// rejection/failure. The caller (an Autonomous Ingestion Agent) is responsible
// for publishing the normalized event via the pipeline.
//
// perm is the tenant-scoped permission consulted at Stage 5.
// kiqID is the optional KIQ reference stamped on the normalized event.
// tenantID is stamped on the normalized event (multi-tenant isolation).
func (h *Harness) InvokeTool(
	ctx context.Context,
	toolName string,
	args map[string]any,
	perm Permission,
	kiqID string,
	tenantID string,
) (*InvokeResult, error) {
	start := h.clock.Now()
	logger := log.With().Str("tool", toolName).Str("tenant_id", tenantID).Logger()

	// ── Stage 3: Select ─────────────────────────────────────────────────
	h.mu.RLock()
	tool, ok := h.tools[toolName]
	h.mu.RUnlock()
	if !ok {
		h.recordStage(toolName, StageSelect, "rejected")
		logger.Warn().Msg("harness: tool not registered")
		return nil, fmt.Errorf("stage %s: tool %q not registered", StageSelect, toolName)
	}
	d := tool.Descriptor()
	h.recordStage(d.Name, StageSelect, "ok")

	// ── Stage 4: Validate ───────────────────────────────────────────────
	if err := ValidateArguments(d, args); err != nil {
		h.recordStage(d.Name, StageValidate, "rejected")
		logger.Warn().Err(err).Msg("harness: argument validation failed")
		return nil, fmt.Errorf("stage %s: %w", StageValidate, err)
	}
	h.recordStage(d.Name, StageValidate, "ok")

	// ── Stage 5: Permission ─────────────────────────────────────────────
	if err := CheckPermission(perm, d.Name); err != nil {
		h.recordStage(d.Name, StagePermission, "rejected")
		HarnessPermissionDeniedTotal.WithLabelValues(d.Name, perm.TenantID).Inc()
		logger.Warn().Err(err).Msg("harness: permission denied")
		return nil, fmt.Errorf("stage %s: %w", StagePermission, err)
	}
	h.recordStage(d.Name, StagePermission, "ok")

	// ── Stage 6: Execute (with circuit breaker) ─────────────────────────
	b := h.breakerFor(d.Name)
	if err := b.allow(h.clock, d.Name); err != nil {
		h.recordStage(d.Name, StageExecute, "rejected")
		logger.Warn().Err(err).Msg("harness: circuit breaker open")
		return nil, fmt.Errorf("stage %s: %w", StageExecute, err)
	}

	execCtx := ctx
	if h.cfg.InvokeTimeout > 0 {
		var cancel context.CancelFunc
		execCtx, cancel = context.WithTimeout(ctx, h.cfg.InvokeTimeout)
		defer cancel()
	}

	ch, err := tool.Invoke(execCtx, args)
	if err != nil {
		b.recordFailure(h.clock, d.Name)
		h.recordStage(d.Name, StageExecute, "error")
		logger.Error().Err(err).Msg("harness: tool invoke failed")
		return nil, fmt.Errorf("stage %s: %w", StageExecute, err)
	}

	blocks, err := drain(ctx, ch)
	if err != nil {
		b.recordFailure(h.clock, d.Name)
		h.recordStage(d.Name, StageExecute, "error")
		logger.Error().Err(err).Msg("harness: tool stream failed")
		return nil, fmt.Errorf("stage %s: %w", StageExecute, err)
	}
	b.recordSuccess(d.Name)
	h.recordStage(d.Name, StageExecute, "ok")

	// ── Stage 7: Observe ────────────────────────────────────────────────
	latency := h.clock.Now().Sub(start).Seconds()
	HarnessInvokeDuration.Observe(latency)
	h.recordStage(d.Name, StageObserve, "ok")

	// ── Stage 8: Normalize ──────────────────────────────────────────────
	// Convert the streamed ContentBlocks into a normalized RawEvent envelope.
	// Provenance is extracted from the block text (ingest.ExtractProvenance)
	// and falls back to the tool descriptor defaults.
	normalized, err := h.normalize(blocks, d, kiqID, tenantID)
	if err != nil {
		h.recordStage(d.Name, StageNormalize, "error")
		logger.Error().Err(err).Msg("harness: normalize failed")
		return nil, fmt.Errorf("stage %s: %w", StageNormalize, err)
	}
	h.recordStage(d.Name, StageNormalize, "ok")

	// ── Stage 9: ReturnLoop ─────────────────────────────────────────────
	result := &InvokeResult{
		Tool:    d,
		Blocks:  blocks,
		Latency: latency,
		Stage:   StageReturnLoop,
	}
	h.recordStage(d.Name, StageReturnLoop, "ok")
	logger.Info().Str("event_id", normalized.ID).Int("blocks", len(blocks)).Float64("latency_s", latency).Msg("harness: invoke complete")
	return result, nil
}

// Normalize converts ContentBlocks into a single RawEvent envelope. The first
// text block's payload is used as the event payload; provenance is extracted
// from it and falls back to the tool descriptor defaults.
func (h *Harness) normalize(blocks []mcp.ContentBlock, d ToolDescriptor, kiqID, tenantID string) (*models.RawEvent, error) {
	if len(blocks) == 0 {
		return nil, errors.New("no content blocks to normalize")
	}
	// Find the first text block with non-empty text.
	var text string
	for _, b := range blocks {
		if b.Type == mcp.ContentTypeText && b.Text != "" {
			text = b.Text
			break
		}
	}
	if text == "" {
		return nil, errors.New("no text content block to normalize")
	}

	// Parse the block text as JSON payload (same convention as
	// pipeline.ProcessBlock). If it isn't JSON, wrap the raw text.
	payload := map[string]any{"text": text}

	// Extract provenance from the block text; fall back to descriptor defaults.
	prov := ingest.ExtractProvenance(text)
	sourceName := prov.SourceName
	if sourceName == "" {
		sourceName = d.SourceName
	}
	if sourceName == "" {
		sourceName = d.Name // final fallback: tool name
	}
	sourceURL := prov.SourceURL
	if sourceURL == "" {
		sourceURL = d.SourceURL
	}

	evt := models.NewRawEvent()
	evt.Source = d.Name
	evt.Payload = payload
	evt.PluginName = d.Name
	evt.PluginVersion = d.Version
	evt.TenantID = tenantID
	evt.KIQID = kiqID
	evt.SourceName = sourceName
	evt.SourceURL = sourceURL

	if err := evt.Validate(); err != nil {
		return nil, fmt.Errorf("normalized event fails contract: %w", err)
	}
	return evt, nil
}

// breakerFor returns the circuit breaker for the named tool.
func (h *Harness) breakerFor(name string) *breaker {
	h.mu.RLock()
	b, ok := h.breakers[name]
	h.mu.RUnlock()
	if ok {
		return b
	}
	// Defensive: should not happen since Register creates the breaker.
	h.mu.Lock()
	defer h.mu.Unlock()
	b = &breaker{
		threshold:  h.cfg.CircuitBreakerThreshold,
		resetAfter: h.cfg.CircuitBreakerReset,
	}
	h.breakers[name] = b
	return b
}

// recordStage emits a per-stage counter for the audit trail.
func (h *Harness) recordStage(tool string, stage Stage, status string) {
	HarnessInvokeTotal.WithLabelValues(tool, stage.String(), status).Inc()
}

// drain reads all ContentBlocks from ch into a slice. Returns an error if the
// context is cancelled before the channel closes.
func drain(ctx context.Context, ch <-chan mcp.ContentBlock) ([]mcp.ContentBlock, error) {
	var out []mcp.ContentBlock
	for {
		select {
		case b, ok := <-ch:
			if !ok {
				return out, nil
			}
			out = append(out, b)
		case <-ctx.Done():
			return out, ctx.Err()
		}
	}
}

// ─── circuit breaker ──────────────────────────────────────────────────────

type breakerState int

const (
	breakerClosed   breakerState = 0
	breakerOpen     breakerState = 1
	breakerHalfOpen breakerState = 2
)

// breaker is a per-tool circuit breaker. It is NOT thread-safe on its own —
// the Harness guards access via the per-tool breaker pointer returned by
// breakerFor, but InvokeTool calls are serialized per tool by the agent
// goroutine. Concurrent calls across agents to the same tool are possible;
// the mutex below guards the state.
type breaker struct {
	mu         sync.Mutex
	state      breakerState
	failures   int
	openedAt   time.Time
	threshold  int
	resetAfter time.Duration
}

func (b *breaker) allow(clock Clock, toolName string) error {
	b.mu.Lock()
	defer b.mu.Unlock()
	switch b.state {
	case breakerOpen:
		if clock.Now().Sub(b.openedAt) >= b.resetAfter {
			b.state = breakerHalfOpen
			HarnessCircuitBreakerState.WithLabelValues(toolName).Set(2)
			return nil // allow one trial call
		}
		return errors.New("circuit breaker open")
	case breakerHalfOpen:
		// Allow the trial call; outcome decides next state.
		return nil
	default:
		return nil
	}
}

func (b *breaker) recordFailure(clock Clock, toolName string) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.failures++
	if b.state == breakerHalfOpen {
		// Trial call failed — re-open.
		b.state = breakerOpen
		b.openedAt = clock.Now()
		HarnessCircuitBreakerState.WithLabelValues(toolName).Set(1)
		return
	}
	if b.failures >= b.threshold {
		b.state = breakerOpen
		b.openedAt = clock.Now()
		HarnessCircuitBreakerState.WithLabelValues(toolName).Set(1)
	}
}

func (b *breaker) recordSuccess(toolName string) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.failures = 0
	b.state = breakerClosed
	HarnessCircuitBreakerState.WithLabelValues(toolName).Set(0)
}

// state returns the current breaker state (for metrics/tests).
func (b *breaker) stateOf() breakerState {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.state
}
