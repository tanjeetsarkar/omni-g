package kafka

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	"github.com/confluentinc/confluent-kafka-go/v2/kafka"
	"github.com/google/uuid"
	"github.com/rs/zerolog/log"
)

// RawEvent is the canonical envelope for all events entering the pipeline.
type RawEvent struct {
	ID              string         `json:"id"`
	Source          string         `json:"source"`
	Timestamp       time.Time      `json:"timestamp"`
	Payload         map[string]any `json:"payload"`
	PluginVersion   string         `json:"plugin_version,omitempty"`
	PluginName      string         `json:"plugin_name,omitempty"`
	IngestLatencyMs int64          `json:"ingest_latency_ms"`
	SchemaVersion   string         `json:"schema_version"`
	TenantID        string         `json:"tenant_id,omitempty"`
}

// Producer wraps confluent-kafka-go and exposes a high-level Publish method.
type Producer struct {
	p     *kafka.Producer
	topic string
}

// NewProducer creates a connected Kafka producer.
// brokers is a comma-separated bootstrap string (e.g. "kafka:9092").
func NewProducer(brokers, topic string) (*Producer, error) {
	p, err := kafka.NewProducer(&kafka.ConfigMap{
		"bootstrap.servers":            brokers,
		"acks":                         "all",
		"retries":                      3,
		"retry.backoff.ms":             200,
		"enable.idempotence":           true,
		"linger.ms":                    10, // micro-batching
		"queue.buffering.max.messages": 100000,
	})
	if err != nil {
		return nil, fmt.Errorf("create kafka producer: %w", err)
	}

	// Start background delivery-report loop.
	go func() {
		for e := range p.Events() {
			switch ev := e.(type) {
			case *kafka.Message:
				if ev.TopicPartition.Error != nil {
					log.Error().
						Err(ev.TopicPartition.Error).
						Str("topic", *ev.TopicPartition.Topic).
						Msg("kafka delivery failed")
				}
			}
		}
	}()

	return &Producer{p: p, topic: topic}, nil
}

// Publish serialises event and enqueues it for delivery. It is non-blocking.
func (pr *Producer) Publish(ctx context.Context, event *RawEvent) error {
	if event.ID == "" {
		event.ID = uuid.New().String()
	}
	if event.Timestamp.IsZero() {
		event.Timestamp = time.Now().UTC()
	}
	if event.SchemaVersion == "" {
		event.SchemaVersion = "1.0"
	}

	payload, err := json.Marshal(event)
	if err != nil {
		return fmt.Errorf("marshal event: %w", err)
	}

	msg := &kafka.Message{
		TopicPartition: kafka.TopicPartition{Topic: &pr.topic, Partition: kafka.PartitionAny},
		Key:            []byte(event.ID),
		Value:          payload,
		Headers: []kafka.Header{
			{Key: "source", Value: []byte(event.Source)},
		},
	}

	if err := pr.p.Produce(msg, nil); err != nil {
		return fmt.Errorf("enqueue message: %w", err)
	}

	return nil
}

// Flush waits for all enqueued messages to be delivered or ctx to be cancelled.
func (pr *Producer) Flush(ctx context.Context) error {
	remaining := pr.p.Flush(int(time.Until(deadline(ctx)).Milliseconds()))
	if remaining > 0 {
		return fmt.Errorf("%d messages not flushed before timeout", remaining)
	}
	return nil
}

// Close flushes and closes the underlying producer.
func (pr *Producer) Close(ctx context.Context) error {
	if err := pr.Flush(ctx); err != nil {
		log.Warn().Err(err).Msg("flush warning on close")
	}
	pr.p.Close()
	return nil
}

func deadline(ctx context.Context) time.Time {
	if dl, ok := ctx.Deadline(); ok {
		return dl
	}
	return time.Now().Add(5 * time.Second)
}
