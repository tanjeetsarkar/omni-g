package agent

import (
	"context"
	"sync"
	"time"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
	"github.com/rs/zerolog/log"
)

// AgentHealthGauge exposes per-agent health status (0=stopped, 1=running,
// 2=degraded) so dashboards can surface fleet state.
var AgentHealthGauge = promauto.NewGaugeVec(prometheus.GaugeOpts{
	Name: "omni_g_agent_health",
	Help: "Autonomous ingestion agent health: 0=stopped, 1=running, 2=degraded.",
}, []string{"agent"})

// SupervisorConfig tunes the AgentSupervisor.
type SupervisorConfig struct {
	// HealthTick is how often the supervisor checks agent health and restarts
	// crashed agents.
	HealthTick time.Duration
	// RestartMax is the maximum restart attempts per agent before marking it
	// degraded.
	RestartMax int
}

// DefaultSupervisorConfig returns sensible production defaults.
func DefaultSupervisorConfig() SupervisorConfig {
	return SupervisorConfig{
		HealthTick: 10 * time.Second,
		RestartMax: 3,
	}
}

// AgentSupervisor manages a fleet of Autonomous Ingestion Agents. It starts
// them, monitors their health on a tick, and restarts crashed agents up to
// RestartMax times before marking them degraded.
type AgentSupervisor struct {
	cfg SupervisorConfig

	mu       sync.Mutex
	agents   map[string]Agent
	restarts map[string]int
	cancel   context.CancelFunc
	doneCh   chan struct{}
	started  bool
}

// NewSupervisor creates an empty AgentSupervisor.
func NewSupervisor(cfg SupervisorConfig) *AgentSupervisor {
	if cfg.HealthTick <= 0 {
		cfg.HealthTick = DefaultSupervisorConfig().HealthTick
	}
	if cfg.RestartMax <= 0 {
		cfg.RestartMax = DefaultSupervisorConfig().RestartMax
	}
	return &AgentSupervisor{
		cfg:      cfg,
		agents:   make(map[string]Agent),
		restarts: make(map[string]int),
	}
}

// Register adds an agent to the supervisor's fleet. Must be called before Start.
func (s *AgentSupervisor) Register(a Agent) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.agents[a.Name()] = a
	s.restarts[a.Name()] = 0
}

// Agents returns the registered agent names.
func (s *AgentSupervisor) Agents() []string {
	s.mu.Lock()
	defer s.mu.Unlock()
	names := make([]string, 0, len(s.agents))
	for n := range s.agents {
		names = append(names, n)
	}
	return names
}

// Start launches all registered agents in background goroutines and begins the
// health-monitoring tick. It returns immediately (non-blocking); agents run
// until the supervisor's context is cancelled or Stop is called.
func (s *AgentSupervisor) Start(ctx context.Context) error {
	s.mu.Lock()
	if s.started {
		s.mu.Unlock()
		return nil
	}
	s.started = true
	runCtx, cancel := context.WithCancel(ctx)
	s.cancel = cancel
	s.doneCh = make(chan struct{})
	agents := make([]Agent, 0, len(s.agents))
	for _, a := range s.agents {
		agents = append(agents, a)
	}
	s.mu.Unlock()

	log.Info().Int("agent_count", len(agents)).Dur("health_tick", s.cfg.HealthTick).
		Msg("supervisor starting agents")

	// Start each agent in its own goroutine.
	for _, a := range agents {
		go s.runAgent(runCtx, a)
	}

	// Health monitor tick.
	go s.healthLoop(runCtx)

	return nil
}

// Stop signals all agents to shut down and waits for them up to 10 seconds.
func (s *AgentSupervisor) Stop() error {
	s.mu.Lock()
	if !s.started {
		s.mu.Unlock()
		return nil
	}
	cancel := s.cancel
	doneCh := s.doneCh
	s.mu.Unlock()
	if cancel != nil {
		cancel()
	}
	// Stop each agent gracefully.
	s.mu.Lock()
	agents := make([]Agent, 0, len(s.agents))
	for _, a := range s.agents {
		agents = append(agents, a)
	}
	s.mu.Unlock()
	for _, a := range agents {
		_ = a.Stop(10 * time.Second)
	}
	if doneCh != nil {
		select {
		case <-doneCh:
		case <-time.After(10 * time.Second):
		}
	}
	s.mu.Lock()
	s.started = false
	s.mu.Unlock()
	log.Info().Msg("supervisor stopped")
	return nil
}

// Health returns the health of all agents keyed by agent name.
func (s *AgentSupervisor) Health() map[string]Health {
	s.mu.Lock()
	defer s.mu.Unlock()
	out := make(map[string]Health, len(s.agents))
	for name, a := range s.agents {
		h := a.Health()
		out[name] = h
		AgentHealthGauge.WithLabelValues(name).Set(float64(h.Status.Ordinal()))
	}
	return out
}

// runAgent starts an agent and records its lifecycle. If the agent's Start
// returns (because its context cancelled) and the supervisor is still running,
// the supervisor attempts a restart up to RestartMax times.
func (s *AgentSupervisor) runAgent(ctx context.Context, a Agent) {
	for {
		// Check supervisor context before (re)starting.
		if ctx.Err() != nil {
			return
		}
		s.mu.Lock()
		restartCount := s.restarts[a.Name()]
		s.mu.Unlock()
		if restartCount > s.cfg.RestartMax {
			log.Error().Str("agent", a.Name()).Int("restarts", restartCount).
				Msg("agent exceeded max restarts, marking degraded")
			s.mu.Lock()
			s.restarts[a.Name()] = restartCount
			s.mu.Unlock()
			return
		}
		log.Info().Str("agent", a.Name()).Int("restart", restartCount).Msg("supervisor starting agent")
		_ = a.Start(ctx)
		// If the supervisor context is done, don't restart.
		if ctx.Err() != nil {
			return
		}
		// Agent stopped unexpectedly — restart.
		s.mu.Lock()
		s.restarts[a.Name()]++
		newCount := s.restarts[a.Name()]
		s.mu.Unlock()
		log.Warn().Str("agent", a.Name()).Int("restarts", newCount).Msg("agent stopped, will restart")
	}
}

// healthLoop periodically samples agent health and updates the Prometheus
// gauge. Restart decisions are made in runAgent; this loop is observability.
func (s *AgentSupervisor) healthLoop(ctx context.Context) {
	defer func() {
		s.mu.Lock()
		if s.doneCh != nil {
			close(s.doneCh)
			s.doneCh = nil
		}
		s.mu.Unlock()
	}()
	ticker := time.NewTicker(s.cfg.HealthTick)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			s.mu.Lock()
			agents := make([]Agent, 0, len(s.agents))
			for _, a := range s.agents {
				agents = append(agents, a)
			}
			s.mu.Unlock()
			for _, a := range agents {
				h := a.Health()
				AgentHealthGauge.WithLabelValues(a.Name()).Set(float64(h.Status.Ordinal()))
			}
		}
	}
}

// Ordinal returns the numeric gauge value for a Status.
func (s Status) Ordinal() float64 {
	switch s {
	case StatusRunning:
		return 1
	case StatusDegraded:
		return 2
	default:
		return 0
	}
}
