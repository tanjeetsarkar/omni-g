package config

import (
	"fmt"
	"strings"

	"github.com/spf13/viper"
)

// Config holds all Aggregator configuration.
type Config struct {
	LogLevel             string   `mapstructure:"LOG_LEVEL"`
	HTTPPort             string   `mapstructure:"HTTP_PORT"`
	KafkaBrokers         []string `mapstructure:"KAFKA_BROKERS"`
	KafkaTopic           string   `mapstructure:"KAFKA_TOPIC"`
	KafkaProducerBatch   int      `mapstructure:"KAFKA_PRODUCER_BATCH_SIZE"`
	KafkaBatchTimeoutMs  int      `mapstructure:"KAFKA_BATCH_TIMEOUT_MS"`
	ValidationServiceURL string   `mapstructure:"VALIDATION_SERVICE_URL"`

	// MCP / Scheduler
	// MCPPluginURLs is the comma-separated list of MCP plugin server base URLs
	// the scheduler will poll (e.g. "http://echo:8090,http://shodan:8091").
	MCPPluginURLs       []string `mapstructure:"MCP_PLUGIN_URLS"`
	SchedulerIntervalMs int      `mapstructure:"SCHEDULER_INTERVAL_MS"`

	// DLQTopic is the Kafka topic for dead-lettered events.
	// Unused in M3.1; wired in M3.4.
	DLQTopic string `mapstructure:"KAFKA_DLQ_TOPIC"`
}

// Load reads configuration from environment variables with sensible defaults.
func Load() (*Config, error) {
	v := viper.New()

	v.SetDefault("LOG_LEVEL", "info")
	v.SetDefault("HTTP_PORT", "8080")
	v.SetDefault("KAFKA_BROKERS", "localhost:9092")
	v.SetDefault("KAFKA_TOPIC", "raw-feed")
	v.SetDefault("KAFKA_PRODUCER_BATCH_SIZE", 100)
	v.SetDefault("KAFKA_BATCH_TIMEOUT_MS", 1000)
	v.SetDefault("VALIDATION_SERVICE_URL", "http://localhost:8001")
	v.SetDefault("MCP_PLUGIN_URLS", "")
	v.SetDefault("SCHEDULER_INTERVAL_MS", 30000)
	v.SetDefault("KAFKA_DLQ_TOPIC", "raw-feed.dlq")

	v.AutomaticEnv()
	v.SetEnvKeyReplacer(strings.NewReplacer(".", "_"))

	cfg := &Config{}
	if err := v.Unmarshal(cfg); err != nil {
		return nil, fmt.Errorf("unmarshal config: %w", err)
	}

	// KAFKA_BROKERS may arrive as a comma-separated string from env.
	if len(cfg.KafkaBrokers) == 1 && strings.Contains(cfg.KafkaBrokers[0], ",") {
		cfg.KafkaBrokers = strings.Split(cfg.KafkaBrokers[0], ",")
	}

	// MCP_PLUGIN_URLS may arrive as a comma-separated string from env.
	if len(cfg.MCPPluginURLs) == 1 && strings.Contains(cfg.MCPPluginURLs[0], ",") {
		cfg.MCPPluginURLs = strings.Split(cfg.MCPPluginURLs[0], ",")
	}
	// Filter empty strings (e.g. when the env var is unset / "").
	filtered := cfg.MCPPluginURLs[:0]
	for _, u := range cfg.MCPPluginURLs {
		if u != "" {
			filtered = append(filtered, u)
		}
	}
	cfg.MCPPluginURLs = filtered

	return cfg, nil
}
