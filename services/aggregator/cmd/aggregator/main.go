package main

import (
	"context"
	"os"
	"os/signal"
	"syscall"

	"github.com/omni-g/aggregator/internal/config"
	"github.com/omni-g/aggregator/internal/server"
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

	srv := server.New(cfg)

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	if err := srv.Start(ctx); err != nil {
		log.Fatal().Err(err).Msg("server exited with error")
	}
}
