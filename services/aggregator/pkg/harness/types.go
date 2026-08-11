// Package harness implements the V4 9-Stage Production Tool Execution
// Lifecycle Harness. Every tool invocation issued by an Autonomous Ingestion
// Agent passes through Harness.InvokeTool(), which runs the nine stages in
// order:
//
//  1. Register   — validate the tool descriptor (JSON schema + risk level).
//  2. Advertise  — expose registered tools to the agent registry.
//  3. Select     — look up the tool by name; reject unknown tools.
//  4. Validate   — enforce argument schema checks against the tool's
//     inputSchema.
//  5. Permission — enforce tenant access control.
//  6. Execute    — run the tool in an isolated call with a circuit breaker.
//  7. Observe    — emit Prometheus latency metrics and Loki-compatible logs.
//  8. Normalize  — format the tool output into a Zero-Mem compliant RawEvent.
//  9. ReturnLoop — return the InvokeResult to the caller (agent publishes).
//
// Stages 1 and 2 happen at registration time; InvokeTool runs stages 3-9.
package harness

import (
	"context"
	"encoding/json"

	"github.com/omni-g/aggregator/internal/mcp"
)

// RiskLevel classifies a tool's blast radius so the permission stage can apply
// tenant-specific policy.
type RiskLevel string

const (
	RiskLow    RiskLevel = "low"
	RiskMedium RiskLevel = "medium"
	RiskHigh   RiskLevel = "high"
)

// Stage enumerates the nine harness stages. The numeric value is used in
// metrics labels and log fields so the audit trail shows which stage ran.
type Stage int

const (
	StageRegister   Stage = iota + 1 // 1
	StageAdvertise                   // 2
	StageSelect                      // 3
	StageValidate                    // 4
	StagePermission                  // 5
	StageExecute                     // 6
	StageObserve                     // 7
	StageNormalize                   // 8
	StageReturnLoop                  // 9
)

// String returns the human-readable stage name for metrics and logs.
func (s Stage) String() string {
	switch s {
	case StageRegister:
		return "register"
	case StageAdvertise:
		return "advertise"
	case StageSelect:
		return "select"
	case StageValidate:
		return "validate"
	case StagePermission:
		return "permission"
	case StageExecute:
		return "execute"
	case StageObserve:
		return "observe"
	case StageNormalize:
		return "normalize"
	case StageReturnLoop:
		return "return_loop"
	default:
		return "unknown"
	}
}

// ToolDescriptor is the metadata registered with the harness (Stage 1). It is
// what Advertise (Stage 2) exposes to agents so they know what they can call.
type ToolDescriptor struct {
	Name        string          `json:"name"`
	Description string          `json:"description"`
	Version     string          `json:"version,omitempty"`
	Risk        RiskLevel       `json:"risk"`
	InputSchema json.RawMessage `json:"inputSchema,omitempty"`
	// SourceName is the default human-readable source name stamped on events
	// produced by this tool when the tool output does not carry one. Defaults
	// to Name when empty.
	SourceName string `json:"source_name,omitempty"`
	// SourceURL is the default human-facing source URL stamped on events when
	// the tool output does not carry one. May be empty.
	SourceURL string `json:"source_url,omitempty"`
}

// Tool is the executable surface a domain service registers with the harness.
// The Execute stage calls Invoke to drive the underlying MCP plugin (or
// in-process implementation) and stream ContentBlocks back.
type Tool interface {
	// Descriptor returns the registered metadata. Must match the descriptor
	// passed to Harness.Register.
	Descriptor() ToolDescriptor
	// Invoke drives the tool and returns a channel of ContentBlocks (the same
	// shape as mcp.Client.CallTool). The channel is closed when the stream
	// ends or ctx is cancelled.
	Invoke(ctx context.Context, args map[string]any) (<-chan mcp.ContentBlock, error)
}

// Permission is the tenant-scoped allow-list consulted by Stage 5. An empty
// AllowedTools slice means "allow all registered tools" — this preserves
// backwards compatibility with untasked general collection where no explicit
// per-tenant policy has been configured.
type Permission struct {
	TenantID     string
	AllowedTools []string
}

// InvokeResult is what InvokeTool returns to the caller after Stage 9. The
// caller (an Autonomous Ingestion Agent) is responsible for publishing the
// normalized event via the pipeline.
type InvokeResult struct {
	Tool    ToolDescriptor
	Blocks  []mcp.ContentBlock
	Latency float64 // seconds
	Stage   Stage   // last stage reached (StageReturnLoop on success)
}
