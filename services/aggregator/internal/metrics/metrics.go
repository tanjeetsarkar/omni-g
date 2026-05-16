package metrics

import (
	"net/http"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

var (
	// IngestTotal counts events entering the pipeline, labelled by source and
	// final status ("published" | "validation_failed" | "publish_error").
	IngestTotal = promauto.NewCounterVec(prometheus.CounterOpts{
		Name: "omni_g_ingest_total",
		Help: "Total events processed by the aggregator pipeline.",
	}, []string{"source", "status"})

	// ValidationFailureTotal tracks schema rejections per source and reason.
	ValidationFailureTotal = promauto.NewCounterVec(prometheus.CounterOpts{
		Name: "omni_g_validation_failure_total",
		Help: "Total events rejected by the validation sidecar.",
	}, []string{"source", "reason"})

	// KafkaPublishTotal counts Kafka produce attempts per topic and status
	// ("ok" | "error").
	KafkaPublishTotal = promauto.NewCounterVec(prometheus.CounterOpts{
		Name: "omni_g_kafka_publish_total",
		Help: "Total Kafka publish attempts.",
	}, []string{"topic", "status"})

	// EventProcessingDuration measures the full validate→publish latency.
	EventProcessingDuration = promauto.NewHistogram(prometheus.HistogramOpts{
		Name:    "omni_g_event_processing_duration_seconds",
		Help:    "End-to-end event processing latency (validate + publish).",
		Buckets: prometheus.DefBuckets,
	})

	// SchedulerPollTotal counts scheduler poll attempts per plugin URL and
	// status ("ok" | "error").
	SchedulerPollTotal = promauto.NewCounterVec(prometheus.CounterOpts{
		Name: "omni_g_scheduler_poll_total",
		Help: "Total MCP plugin poll attempts by the scheduler.",
	}, []string{"plugin_url", "status"})

	// KafkaQueueDepth exposes the number of messages buffered in the producer
	// queue. Updated on each publish.
	KafkaQueueDepth = promauto.NewGauge(prometheus.GaugeOpts{
		Name: "omni_g_kafka_queue_depth",
		Help: "Current number of messages buffered in the Kafka producer queue.",
	})
)

// Handler returns an http.Handler that serves the Prometheus metrics page.
func Handler() http.Handler {
	return promhttp.Handler()
}
