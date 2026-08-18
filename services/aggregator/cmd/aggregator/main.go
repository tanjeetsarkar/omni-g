package main

import (
	"context"
	"encoding/json"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"github.com/omni-g/aggregator/internal/config"
	"github.com/omni-g/aggregator/internal/kafka"
	"github.com/omni-g/aggregator/internal/mcp"
	_ "github.com/omni-g/aggregator/internal/metrics" // register Prometheus metrics via promauto
	"github.com/omni-g/aggregator/internal/pipeline"
	"github.com/omni-g/aggregator/internal/registry"
	"github.com/omni-g/aggregator/internal/server"
	"github.com/omni-g/aggregator/internal/validation"
	"github.com/omni-g/aggregator/pkg/agent"
	"github.com/omni-g/aggregator/pkg/harness"
	"github.com/rs/zerolog"
	"github.com/rs/zerolog/log"
)

func main() {
	cfg, err := config.Load()
	if err != nil {
		log.Fatal().Err(err).Msg("failed to load config")
	}

	level, err := zerolog.ParseLevel(cfg.LogLevel)
	if err != nil {
		level = zerolog.InfoLevel
	}
	zerolog.SetGlobalLevel(level)
	log.Logger = log.Output(zerolog.ConsoleWriter{Out: os.Stderr}).With().
		Str("service", "aggregator").
		Logger()
	log.Info().
		Str("log_level", level.String()).
		Str("http_port", cfg.HTTPPort).
		Strs("kafka_brokers", cfg.KafkaBrokers).
		Str("kafka_topic", cfg.KafkaTopic).
		Str("tenant_id", cfg.TenantID).
		Msg("aggregator starting")

	// ── Kafka producer ────────────────────────────────────────────────────
	producer, err := kafka.NewProducer(strings.Join(cfg.KafkaBrokers, ","), cfg.KafkaTopic)
	if err != nil {
		log.Fatal().Err(err).Msg("failed to create kafka producer")
	}

	// ── Validation sidecar ────────────────────────────────────────────────
	validator := validation.NewValidator(cfg.ValidationServiceURL)

	// ── Processing pipeline ───────────────────────────────────────────────
	pl := pipeline.New(validator, producer, cfg.KafkaTopic, cfg.TenantID)

	// ── V4 Track 3: Tool Governance Harness ───────────────────────────────
	harnessCfg := harness.Config{
		InvokeTimeout:           time.Duration(cfg.HarnessInvokeTimeoutMs) * time.Millisecond,
		CircuitBreakerThreshold: cfg.HarnessCircuitBreakerThreshold,
		CircuitBreakerReset:     time.Duration(cfg.HarnessCircuitBreakerResetMs) * time.Millisecond,
	}
	h := harness.New(harnessCfg, nil)

	// ── Plugin Registry (replaces mu-centric tool registry) ────────────────
	// Plugins are discovered from plugins.yaml at startup. Each plugin runs as
	// an independent MCP server (websearch, newsearch, etc.).
	pluginRegistry, err := registry.NewPluginRegistry(cfg.PluginsConfigPath, h)
	if err != nil {
		log.Warn().Err(err).Msg("failed to create plugin registry, continuing with empty registry")
	} else {
		discoverCtx, discoverCancel := context.WithTimeout(context.Background(), 60*time.Second)
		registered, regErr := pluginRegistry.RegisterAll(discoverCtx)
		discoverCancel()
		if regErr != nil {
			log.Warn().Err(regErr).Msg("plugin registry registration completed with errors")
		}
		log.Info().Int("tools_registered", registered).Msg("plugin registry initialized")
	}

	// ── MCP discovery handler ─────────────────────────────────────────────
	mcpHandler := mcp.NewHandler()

	// Populate the MCP discovery handler from the harness registry so
	// GET /mcp/tools reflects all governed tools (mu + legacy).
	for _, d := range h.Advertise() {
		mcpHandler.RegisterTool(mcp.Tool{
			Name:        d.Name,
			Description: d.Description,
			Version:     d.Version,
			InputSchema: d.InputSchema,
		})
	}

	// ── V5: AgenticRouter (OpenRouter-driven tool selection) ──────────────
	router := agent.NewAgenticRouter(agent.RouterConfig{
		OpenRouterAPIKey: cfg.OpenRouterAPIKey,
		OpenRouterModel:  cfg.OpenRouterModel,
		MaxTools:         cfg.RouterMaxTools,
		Timeout:          time.Duration(cfg.RouterTimeoutMs) * time.Millisecond,
		Harness:          h,
		TenantID:         cfg.TenantID,
	})
	if cfg.OpenRouterAPIKey != "" {
		log.Info().Str("model", cfg.OpenRouterModel).Msg("agentic router initialized with OpenRouter")
	} else {
		log.Warn().Msg("agentic router running in fallback mode (no OPENROUTER_API_KEY set)")
	}

	// ── V5: QueryAgent (autonomous KIQ-driven collection) ─────────────────
	// V5.1: Autonomous collection is disabled. All collection is driven by
	// on-demand /search requests from the Delivery UI, which route through
	// the AgenticRouter for intelligent tool selection.
	//
	// The WatcherAgent (streaming ingestion) is still available for tools
	// that support SSE/WebSocket streams.
	supervisor := agent.NewSupervisor(agent.SupervisorConfig{
		HealthTick: time.Duration(cfg.AgentHealthTickMs) * time.Millisecond,
		RestartMax: cfg.AgentRestartMax,
	})

	// ── V4 Track 3: WatcherAgent (streaming ingestion) ────────────────────
	if cfg.WatcherEnabled && cfg.WatcherTool != "" {
		var watcherArgs map[string]any
		if cfg.WatcherArgs != "" {
			if err := json.Unmarshal([]byte(cfg.WatcherArgs), &watcherArgs); err != nil {
				log.Warn().Err(err).Str("watcher_args", cfg.WatcherArgs).
					Msg("failed to parse WATCHER_ARGS as JSON; watcher will call tool with no args")
			}
		}
		watcher := agent.NewWatcherAgent(agent.WatcherConfig{
			Name:       "watcher-" + cfg.WatcherTool,
			Harness:    h,
			ToolName:   cfg.WatcherTool,
			Args:       watcherArgs,
			TenantID:   cfg.TenantID,
			Permission: harness.Permission{TenantID: cfg.TenantID},
			OnResult: func(ctx context.Context, result *harness.InvokeResult) error {
				for _, block := range result.Blocks {
					if block.Type != mcp.ContentTypeText || block.Text == "" {
						continue
					}
					if err := pl.ProcessBlock(ctx, pipeline.SourceForTool(result.Tool.Name, result.Tool.SourceURL), block.Text,
						result.Tool.Name, result.Tool.Version, "", result.Tool.SourceName, result.Tool.SourceURL, ""); err != nil {
						log.Warn().Str("tool", result.Tool.Name).Err(err).Msg("pipeline.ProcessBlock error from watcher")
					}
				}
				return nil
			},
		})
		supervisor.Register(watcher)
		log.Info().Str("watcher_tool", cfg.WatcherTool).Msg("watcher agent registered")
	}

	// ── HTTP server ───────────────────────────────────────────────────────
	// V5: SearchHandler uses the AgenticRouter for dynamic tool selection
	// across all mu-discovered tools. No hardcoded source→tool map needed.
	searchHandler := server.NewSearchHandler(pl, h, cfg.TenantID)
	// Inject the router for intelligent tool selection on /search and /enrich.
	searchHandler.SetRouter(router)

	srv := server.New(cfg, pl, supervisor, mcpHandler, searchHandler)

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	// Start the autonomous ingestion agents (non-blocking).
	if err := supervisor.Start(ctx); err != nil {
		log.Fatal().Err(err).Msg("failed to start agent supervisor")
	}

	log.Info().Str("http_port", cfg.HTTPPort).Msg("aggregator server starting")
	if err := srv.Start(ctx); err != nil {
		log.Fatal().Err(err).Msg("server exited with error")
	}
	log.Info().Msg("aggregator shutting down")

	// Stop the agent supervisor gracefully.
	if err := supervisor.Stop(); err != nil {
		log.Warn().Err(err).Msg("agent supervisor stop warning")
	}

	// Flush remaining Kafka messages on graceful shutdown.
	flushCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := producer.Close(flushCtx); err != nil {
		log.Warn().Err(err).Msg("kafka producer close warning")
	}
	log.Info().Msg("aggregator shutdown complete")
}
