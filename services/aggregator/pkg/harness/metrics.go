package harness

import (
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
)

// Harness metrics. All are labelled so the Milestone 5 governance audit can
// verify that every stage of every invocation is observable.
var (
	// HarnessInvokeTotal counts tool invocations per tool, per stage reached,
	// per terminal status ("ok" | "rejected" | "error"). Stage labels let the
	// audit confirm all 9 stages ran for a successful call.
	HarnessInvokeTotal = promauto.NewCounterVec(prometheus.CounterOpts{
		Name: "omni_g_harness_invoke_total",
		Help: "Tool invocations through the 9-stage harness, by tool/stage/status.",
	}, []string{"tool", "stage", "status"})

	// HarnessInvokeDuration measures the full InvokeTool latency per tool.
	HarnessInvokeDuration = promauto.NewHistogram(prometheus.HistogramOpts{
		Name:    "omni_g_harness_invoke_duration_seconds",
		Help:    "End-to-end harness InvokeTool latency per tool.",
		Buckets: prometheus.DefBuckets,
	})

	// HarnessCircuitBreakerState exposes the per-tool circuit breaker state
	// (0=closed, 1=open, 2=half-open) so dashboards can surface degradation.
	HarnessCircuitBreakerState = promauto.NewGaugeVec(prometheus.GaugeOpts{
		Name: "omni_g_harness_circuit_breaker_state",
		Help: "Per-tool circuit breaker state: 0=closed, 1=open, 2=half-open.",
	}, []string{"tool"})

	// HarnessPermissionDeniedTotal counts Stage 5 rejections per tool/tenant.
	HarnessPermissionDeniedTotal = promauto.NewCounterVec(prometheus.CounterOpts{
		Name: "omni_g_harness_permission_denied_total",
		Help: "Stage 5 permission denials per tool and tenant.",
	}, []string{"tool", "tenant"})
)
