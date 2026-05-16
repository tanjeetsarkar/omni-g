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

	return cfg, nil
}
