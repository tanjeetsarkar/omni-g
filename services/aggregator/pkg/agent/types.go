// Package agent implements the V4 Autonomous Ingestion Agents that drive
// collection through the Tool Governance Harness. Three agent types are
// provided:
//
//   - PollerAgent: executes background interval/cron fetches using tools
//     registered in the Harness.
//   - WatcherAgent: maintains long-lived SSE/WebSocket streams with
//     auto-reconnect backoff.
//   - AgentSupervisor: monitors agent health, manages the runtime lifecycle,
//     and recovers failed agents.
package agent

import (
	"context"
	"time"
)

// Status enumerates the runtime state of an agent.
type Status string

const (
	StatusRunning  Status = "running"
	StatusDegraded Status = "degraded"
	StatusStopped  Status = "stopped"
)

// Health reports an agent's runtime state for the supervisor and the
// /agents/health endpoint.
type Health struct {
	Status     Status     `json:"status"`
	LastRun    *time.Time `json:"last_run,omitempty"`
	ErrorCount int        `json:"error_count"`
	LastError  string     `json:"last_error,omitempty"`
	Restarts   int        `json:"restarts"`
}

// Agent is the common interface implemented by PollerAgent, WatcherAgent, and
// any future agent type. The AgentSupervisor manages a fleet of Agents.
type Agent interface {
	// Name returns the agent's unique identifier.
	Name() string
	// Start launches the agent's collection loop. It blocks until ctx is
	// cancelled or Stop is called. Start is idempotent: calling it on an
	// already-running agent is a no-op.
	Start(ctx context.Context) error
	// Stop signals the agent to shut down gracefully. It waits for in-flight
	// work to complete up to the given timeout.
	Stop(timeout time.Duration) error
	// Health returns the agent's current runtime state.
	Health() Health
}
