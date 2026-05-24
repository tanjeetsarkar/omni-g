package server

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"time"

	"github.com/omni-g/aggregator/internal/config"
	"github.com/omni-g/aggregator/internal/mcp"
	"github.com/omni-g/aggregator/internal/metrics"
	"github.com/omni-g/aggregator/internal/pipeline"
	"github.com/omni-g/aggregator/internal/scheduler"
	"github.com/rs/zerolog/log"
)

const (
	readTimeout  = 5 * time.Second
	writeTimeout = 10 * time.Second
	idleTimeout  = 120 * time.Second
)

// Server is the HTTP server for the Aggregator.
type Server struct {
	cfg           *config.Config
	mux           *http.ServeMux
	httpSrv       *http.Server
	pipeline      *pipeline.Pipeline
	scheduler     *scheduler.Scheduler
	mcpHandler    *mcp.Handler
	searchHandler *SearchHandler
}

// New creates a configured Server.
//
// pipeline, sched, mcpHandler, and searchHandler may be nil (e.g. in
// health-only tests); their routes are still registered but are no-ops in
// that case.
func New(cfg *config.Config, pl *pipeline.Pipeline, sched *scheduler.Scheduler, mcpHandler *mcp.Handler, searchHandler *SearchHandler) *Server {
	s := &Server{
		cfg:           cfg,
		mux:           http.NewServeMux(),
		pipeline:      pl,
		scheduler:     sched,
		mcpHandler:    mcpHandler,
		searchHandler: searchHandler,
	}
	s.registerRoutes()
	s.httpSrv = &http.Server{
		Addr:         fmt.Sprintf(":%s", cfg.HTTPPort),
		Handler:      s.mux,
		ReadTimeout:  readTimeout,
		WriteTimeout: writeTimeout,
		IdleTimeout:  idleTimeout,
	}
	return s
}

func (s *Server) registerRoutes() {
	s.mux.HandleFunc("GET /health", s.handleHealth)
	s.mux.HandleFunc("GET /ready", s.handleReady)
	s.mux.HandleFunc("GET /mcp/tools", s.handleMCPTools)
	s.mux.Handle("GET /metrics", metrics.Handler())
	if s.searchHandler != nil {
		s.mux.Handle("POST /search", s.searchHandler)
	}
}

// ServeHTTP implements http.Handler so Server can be used directly in tests.
func (s *Server) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	s.mux.ServeHTTP(w, r)
}

// Start begins listening and blocks until ctx is cancelled.
// The scheduler (if set) is started in a background goroutine wired to the
// pipeline.
func (s *Server) Start(ctx context.Context) error {
	if s.scheduler != nil && s.pipeline != nil {
		go s.scheduler.Start(ctx, func(ctx context.Context, source string, block mcp.ContentBlock, tool mcp.Tool) error {
			if block.Type != mcp.ContentTypeText || block.Text == "" {
				return nil
			}
			version := tool.Version
			if version == "" {
				version = "unknown"
			}
			return s.pipeline.ProcessBlock(ctx, source, block.Text, tool.Name, version)
		})
	}

	errCh := make(chan error, 1)

	go func() {
		log.Info().Str("addr", s.httpSrv.Addr).Msg("HTTP server starting")
		if err := s.httpSrv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			errCh <- err
		}
	}()

	select {
	case <-ctx.Done():
		log.Info().Msg("shutting down HTTP server")
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		return s.httpSrv.Shutdown(shutdownCtx)
	case err := <-errCh:
		return err
	}
}

// ─── handlers ────────────────────────────────────────────────────────────────

// healthResponse is returned by /health and /ready.
type healthResponse struct {
	Status  string `json:"status"`
	Service string `json:"service"`
}

func (s *Server) handleHealth(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, healthResponse{Status: "ok", Service: "aggregator"})
}

func (s *Server) handleReady(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, healthResponse{Status: "ready", Service: "aggregator"})
}

func (s *Server) handleMCPTools(w http.ResponseWriter, r *http.Request) {
	if s.mcpHandler == nil {
		writeJSON(w, http.StatusOK, mcp.JSONRPCResponse{
			JSONRPC: "2.0",
			Result:  mustMarshal(mcp.ToolsListResult{Tools: []mcp.Tool{}}),
		})
		return
	}
	s.mcpHandler.HandleToolsList(w, r)
}

func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if err := json.NewEncoder(w).Encode(body); err != nil {
		log.Error().Err(err).Msg("failed to write JSON response")
	}
}

func mustMarshal(v any) json.RawMessage {
	b, _ := json.Marshal(v)
	return json.RawMessage(b)
}
