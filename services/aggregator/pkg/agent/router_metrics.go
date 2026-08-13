package agent

import (
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
)

// RouterMetrics exposes Prometheus metrics for the AgenticRouter.
var (
	// RouterCallsTotal counts router invocations by model and status.
	RouterCallsTotal = promauto.NewCounterVec(prometheus.CounterOpts{
		Name: "omni_g_router_calls_total",
		Help: "Total number of AgenticRouter invocations.",
	}, []string{"model", "status"})

	// RouterToolsSelected is a histogram of how many tools the router selects per query.
	RouterToolsSelected = promauto.NewHistogram(prometheus.HistogramOpts{
		Name:    "omni_g_router_tools_selected",
		Help:    "Number of tools selected by the router per query.",
		Buckets: []float64{0, 1, 2, 3, 5, 10},
	})

	// RouterLatencySeconds is a histogram of router LLM call latency.
	RouterLatencySeconds = promauto.NewHistogram(prometheus.HistogramOpts{
		Name:    "omni_g_router_latency_seconds",
		Help:    "Latency of AgenticRouter LLM calls in seconds.",
		Buckets: []float64{0.1, 0.5, 1, 2, 5, 10, 30},
	})
)
