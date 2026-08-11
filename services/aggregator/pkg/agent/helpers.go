package agent

import (
	"encoding/json"
	"math"
	"time"

	"github.com/omni-g/aggregator/internal/mcp"
	"github.com/omni-g/aggregator/pkg/harness"
)

const (
	maxRetries = 5
	maxBackoff = 60 * time.Second
)

// backoffDuration returns the exponential backoff for the given attempt
// number, capped at maxBackoff. Mirrors the logic in the deprecated
// internal/scheduler so agents inherit the same retry cadence.
func backoffDuration(attempt int) time.Duration {
	d := time.Duration(math.Pow(2, float64(attempt))) * 500 * time.Millisecond
	if d > maxBackoff {
		return maxBackoff
	}
	return d
}

// toolHasRequiredParams reports whether a tool descriptor's inputSchema
// declares any required parameters. Tools with required params cannot be
// polled by the PollerAgent (which calls them with nil arguments); they must
// be invoked explicitly via POST /search with a user-supplied query.
func toolHasRequiredParams(d harness.ToolDescriptor) bool {
	if len(d.InputSchema) == 0 {
		return false
	}
	var schema struct {
		Required []string `json:"required"`
	}
	if err := json.Unmarshal(d.InputSchema, &schema); err != nil {
		return false
	}
	return len(schema.Required) > 0
}

// toolHasRequiredParamsMCP is the legacy helper kept for compatibility with
// code paths that still hold an mcp.Tool. Prefer toolHasRequiredParams with
// a harness.ToolDescriptor.
func toolHasRequiredParamsMCP(tool mcp.Tool) bool {
	if len(tool.InputSchema) == 0 {
		return false
	}
	var schema struct {
		Required []string `json:"required"`
	}
	if err := json.Unmarshal(tool.InputSchema, &schema); err != nil {
		return false
	}
	return len(schema.Required) > 0
}
