package kafka_test

import (
	"testing"
	"time"

	"github.com/omni-g/aggregator/internal/kafka"
	"github.com/stretchr/testify/assert"
)

func TestRawEventDefaults(t *testing.T) {
	tests := []struct {
		name  string
		event kafka.RawEvent
	}{
		{
			name: "event with all fields set",
			event: kafka.RawEvent{
				ID:        "test-id",
				Source:    "twitter",
				Timestamp: time.Now(),
				Payload:   map[string]any{"text": "hello"},
			},
		},
		{
			name: "minimal event",
			event: kafka.RawEvent{
				Source:  "shodan",
				Payload: map[string]any{"ip": "1.2.3.4"},
			},
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			assert.NotEmpty(t, tc.event.Source)
			assert.NotNil(t, tc.event.Payload)
		})
	}
}
