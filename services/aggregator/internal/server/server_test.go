package server_test

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/omni-g/aggregator/internal/config"
	"github.com/omni-g/aggregator/internal/server"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func testConfig() *config.Config {
	return &config.Config{
		LogLevel: "disabled",
		HTTPPort: "8080",
	}
}

func TestHealthEndpoint(t *testing.T) {
	tests := []struct {
		name           string
		path           string
		expectedStatus int
		expectedBody   string
	}{
		{
			name:           "health returns 200",
			path:           "/health",
			expectedStatus: http.StatusOK,
			expectedBody:   "ok",
		},
		{
			name:           "ready returns 200",
			path:           "/ready",
			expectedStatus: http.StatusOK,
			expectedBody:   "ready",
		},
	}

	srv := server.New(testConfig())

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			req := httptest.NewRequest(http.MethodGet, tc.path, nil)
			rec := httptest.NewRecorder()

			srv.ServeHTTP(rec, req)

			assert.Equal(t, tc.expectedStatus, rec.Code)

			var body map[string]string
			require.NoError(t, json.NewDecoder(rec.Body).Decode(&body))
			assert.Equal(t, tc.expectedBody, body["status"])
			assert.Equal(t, "aggregator", body["service"])
		})
	}
}

func TestUnknownRouteReturns404(t *testing.T) {
	srv := server.New(testConfig())

	req := httptest.NewRequest(http.MethodGet, "/unknown", nil)
	rec := httptest.NewRecorder()

	srv.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusNotFound, rec.Code)
}
