package main

import (
	"context"
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
	"github.com/omni-g/aggregator/internal/scheduler"
	"github.com/omni-g/aggregator/internal/server"
	"github.com/omni-g/aggregator/internal/validation"
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

	// ── Kafka producer ────────────────────────────────────────────────────
	producer, err := kafka.NewProducer(strings.Join(cfg.KafkaBrokers, ","), cfg.KafkaTopic)
	if err != nil {
		log.Fatal().Err(err).Msg("failed to create kafka producer")
	}

	// ── Validation sidecar ────────────────────────────────────────────────
	validator := validation.NewValidator(cfg.ValidationServiceURL)

	// ── Processing pipeline ───────────────────────────────────────────────
	pl := pipeline.New(validator, producer, cfg.KafkaTopic)

	// ── Agentic scheduler ─────────────────────────────────────────────────
	sched := scheduler.New()
	interval := time.Duration(cfg.SchedulerIntervalMs) * time.Millisecond
	for _, u := range cfg.MCPPluginURLs {
		sched.RegisterPlugin(u, interval)
		log.Info().Str("plugin", u).Dur("interval", interval).Msg("registered MCP plugin")
	}

	// ── MCP discovery handler ─────────────────────────────────────────────
	mcpHandler := mcp.NewHandler()
	for _, u := range cfg.MCPPluginURLs {
		mcpHandler.RegisterTool(mcp.Tool{
			Name:        u,
			Description: "MCP plugin data source",
		})
	}

	// ── HTTP server ───────────────────────────────────────────────────────
	srv := server.New(cfg, pl, sched, mcpHandler)

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	if err := srv.Start(ctx); err != nil {
		log.Fatal().Err(err).Msg("server exited with error")
	}

	// Flush remaining Kafka messages on graceful shutdown.
	flushCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := producer.Close(flushCtx); err != nil {
		log.Warn().Err(err).Msg("kafka producer close warning")
	}
}
