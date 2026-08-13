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

	// DLQTopic is the Kafka topic for dead-lettered events.
	// Unused in M3.1; wired in M3.4.
	DLQTopic string `mapstructure:"KAFKA_DLQ_TOPIC"`

	// TenantID identifies the tenant for all events produced by this instance.
	TenantID string `mapstructure:"TENANT_ID"`

	// ── V4 Track 3: Harness & Agent governance knobs ───────────────────────
	// HarnessInvokeTimeoutMs caps a single governed tool invocation.
	HarnessInvokeTimeoutMs int `mapstructure:"HARNESS_INVOKE_TIMEOUT_MS"`
	// HarnessCircuitBreakerThreshold is the consecutive failure count that
	// opens the per-tool circuit breaker.
	HarnessCircuitBreakerThreshold int `mapstructure:"HARNESS_CIRCUIT_BREAKER_THRESHOLD"`
	// HarnessCircuitBreakerResetMs is how long the breaker stays open before
	// moving to half-open.
	HarnessCircuitBreakerResetMs int `mapstructure:"HARNESS_CIRCUIT_BREAKER_RESET_MS"`
	// AgentHealthTickMs is how often the supervisor samples agent health.
	AgentHealthTickMs int `mapstructure:"AGENT_HEALTH_TICK_MS"`
	// AgentRestartMax is the max restart attempts per agent before degraded.
	AgentRestartMax int `mapstructure:"AGENT_RESTART_MAX"`

	// ── WatcherAgent (streaming ingestion) ────────────────────────────────
	// WatcherEnabled controls whether a WatcherAgent is registered with the
	// supervisor. When true, the watcher continuously calls WatcherTool and
	// reconnects on stream end, turning any pollable tool into a live watch.
	WatcherEnabled bool `mapstructure:"WATCHER_ENABLED"`
	// WatcherTool is the governed tool name the watcher monitors.
	WatcherTool string `mapstructure:"WATCHER_TOOL"`
	// WatcherArgs is an optional JSON-encoded argument map passed to the
	// watcher tool on each (re)connect (e.g. {"query":"breaking news"}).
	WatcherArgs string `mapstructure:"WATCHER_ARGS"`

	// ── Mu / Agentic Router ──────────────────────────────────────────────
	// MuMCPURL is the MCP endpoint of the micro/mu sidecar.
	MuMCPURL string `mapstructure:"MU_MCP_URL"`
	// MuEnabled controls whether mu tool discovery runs on startup.
	MuEnabled bool `mapstructure:"MU_ENABLED"`
	// ToolsConfigPath is the path to the YAML/JSON tool registry config.
	ToolsConfigPath string `mapstructure:"TOOLS_CONFIG_PATH"`
	// OpenRouterAPIKey is the API key for OpenRouter (used by AgenticRouter).
	OpenRouterAPIKey string `mapstructure:"OPENROUTER_API_KEY"`
	// OpenRouterModel is the model used for tool selection routing.
	OpenRouterModel string `mapstructure:"OPENROUTER_MODEL"`
	// RouterMaxTools caps the number of tools the router can select per query.
	RouterMaxTools int `mapstructure:"ROUTER_MAX_TOOLS"`
	// RouterTimeoutMs caps the router LLM call duration.
	RouterTimeoutMs int `mapstructure:"ROUTER_TIMEOUT_MS"`
	// AgentQueries is a comma-separated list of standing queries for QueryAgent.
	AgentQueries string `mapstructure:"AGENT_QUERIES"`
	// AgentQueryIntervalMs is the interval between QueryAgent query cycles.
	AgentQueryIntervalMs int `mapstructure:"AGENT_QUERY_INTERVAL_MS"`
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
	v.SetDefault("KAFKA_DLQ_TOPIC", "raw-feed.dlq")
	v.SetDefault("TENANT_ID", "default")

	// V4 Track 3: harness & agent defaults.
	v.SetDefault("HARNESS_INVOKE_TIMEOUT_MS", 30000)
	v.SetDefault("HARNESS_CIRCUIT_BREAKER_THRESHOLD", 5)
	v.SetDefault("HARNESS_CIRCUIT_BREAKER_RESET_MS", 30000)
	v.SetDefault("AGENT_HEALTH_TICK_MS", 10000)
	v.SetDefault("AGENT_RESTART_MAX", 3)

	// WatcherAgent defaults.
	v.SetDefault("WATCHER_ENABLED", false)
	v.SetDefault("WATCHER_TOOL", "search_news")
	v.SetDefault("WATCHER_ARGS", "")

	// ── Mu / Agentic Router defaults ────────────────────────────────────
	v.SetDefault("MU_MCP_URL", "http://localhost:8080/mcp")
	v.SetDefault("MU_ENABLED", true)
	v.SetDefault("TOOLS_CONFIG_PATH", "tools.yaml")
	v.SetDefault("OPENROUTER_API_KEY", "")
	v.SetDefault("OPENROUTER_MODEL", "openrouter/free")
	v.SetDefault("ROUTER_MAX_TOOLS", 5)
	v.SetDefault("ROUTER_TIMEOUT_MS", 30000)
	v.SetDefault("AGENT_QUERIES", "")
	v.SetDefault("AGENT_QUERY_INTERVAL_MS", 300000) // 5 min default

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
