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
	"github.com/omni-g/aggregator/internal/server"
	"github.com/omni-g/aggregator/internal/services"
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
		Int("mcp_plugins", len(cfg.MCPPluginURLs)).
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

	// ── V4 Track 3: Micro/Mu domain services ──────────────────────────────
	svcCfg := services.ServiceConfig{
		NewsRSSPluginURL:   cfg.NewsRSSPluginURL,
		ReutersPluginURL:   cfg.ReutersPluginURL,
		WikipediaPluginURL: cfg.WikipediaPluginURL,
		WikidataPluginURL:  cfg.WikidataPluginURL,
	}
	registered := 0
	for _, svc := range services.All(svcCfg) {
		if err := svc.Register(h); err != nil {
			log.Error().Str("service", svc.Name()).Err(err).Msg("failed to register domain service")
		} else {
			registered++
		}
	}
	log.Info().Int("services_registered", registered).Msg("domain services registered")

	// ── MCP discovery handler ─────────────────────────────────────────────
	mcpHandler := mcp.NewHandler()

	// Initial discovery: contact each plugin to populate the tool registry.
	{
		discoverCtx, discoverCancel := context.WithTimeout(context.Background(), 30*time.Second)
		for _, u := range cfg.MCPPluginURLs {
			tools, err := mcpHandler.DiscoverTools(discoverCtx, u)
			if err != nil {
				log.Warn().Str("plugin", u).Err(err).Msg("initial tool discovery failed, will retry on next poll")
			} else {
				log.Info().Str("plugin", u).Int("tools", len(tools)).Msg("tool discovery succeeded")
			}
		}
		discoverCancel()
	}

	// Populate the MCP discovery handler from the harness registry so
	// GET /mcp/tools reflects the governed tools (replaces the deprecated
	// scheduler.SetOnDiscovery refresh path).
	for _, d := range h.Advertise() {
		mcpHandler.RegisterTool(mcp.Tool{
			Name:        d.Name,
			Description: d.Description,
			Version:     d.Version,
			InputSchema: d.InputSchema,
		})
	}

	// ── V4 Track 3: Autonomous Ingestion Agents ───────────────────────────
	pollInterval := time.Duration(cfg.SchedulerIntervalMs) * time.Millisecond
	poller := agent.NewPollerAgent(agent.PollerConfig{
		Name:       "poller-default",
		Harness:    h,
		Interval:   pollInterval,
		TenantID:   cfg.TenantID,
		Permission: harness.Permission{TenantID: cfg.TenantID}, // allow-all
		OnResult: func(ctx context.Context, result *harness.InvokeResult) error {
			// Publish each block through the pipeline (validate → publish).
			for _, block := range result.Blocks {
				if block.Type != mcp.ContentTypeText || block.Text == "" {
					continue
				}
				if err := pl.ProcessBlock(ctx, pipeline.SourceForTool(result.Tool.Name, result.Tool.SourceURL), block.Text,
					result.Tool.Name, result.Tool.Version, "", result.Tool.SourceName, result.Tool.SourceURL); err != nil {
					log.Warn().Str("tool", result.Tool.Name).Err(err).Msg("pipeline.ProcessBlock error from poller")
				}
			}
			return nil
		},
	})

	supervisor := agent.NewSupervisor(agent.SupervisorConfig{
		HealthTick: time.Duration(cfg.AgentHealthTickMs) * time.Millisecond,
		RestartMax: cfg.AgentRestartMax,
	})
	supervisor.Register(poller)
	log.Info().Dur("poll_interval", pollInterval).Msg("poller agent registered")

	// ── V4 Track 3: WatcherAgent (streaming ingestion) ────────────────────
	// When enabled, the watcher continuously calls the configured governed
	// tool and reconnects on stream end, turning any pollable tool into a
	// live watch. All calls route through the 9-stage harness.
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
			Permission: harness.Permission{TenantID: cfg.TenantID}, // allow-all
			OnResult: func(ctx context.Context, result *harness.InvokeResult) error {
				for _, block := range result.Blocks {
					if block.Type != mcp.ContentTypeText || block.Text == "" {
						continue
					}
					if err := pl.ProcessBlock(ctx, pipeline.SourceForTool(result.Tool.Name, result.Tool.SourceURL), block.Text,
						result.Tool.Name, result.Tool.Version, "", result.Tool.SourceName, result.Tool.SourceURL); err != nil {
						log.Warn().Str("tool", result.Tool.Name).Err(err).Msg("pipeline.ProcessBlock error from watcher")
					}
				}
				return nil
			},
		})
		supervisor.Register(watcher)
		log.Info().Str("watcher_tool", cfg.WatcherTool).Msg("watcher agent registered")
	}

	// NOTE: The legacy internal/scheduler is deprecated as of V4 Track 3.
	// Autonomous agents (pkg/agent) + the 9-stage harness replace it. The
	// scheduler package is retained for one release to support rolling
	// upgrades but is no longer wired here.

	// ── HTTP server ───────────────────────────────────────────────────────
	// /search and /enrich route through the 9-stage harness via the
	// SearchHandler. The source→tool map references the governed tool names
	// registered by the domain services (web_search, search_news, etc.).
	searchHandler := server.NewSearchHandler(
		map[string]string{
			"wikipedia": "web_search",
			"wikidata":  "web_search",
			"newsrss":   "search_news",
			"reuters":   "search_news",
			"feeds":     "fetch_feed",
			"weather":   "fetch_weather",
		},
		pl,
		h,
		cfg.TenantID,
	)

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
