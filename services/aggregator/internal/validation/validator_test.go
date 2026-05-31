package validation_test

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/omni-g/aggregator/internal/validation"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestValidator_ValidPayload(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		assert.Equal(t, "/validate", r.URL.Path)
		assert.Equal(t, "application/json", r.Header.Get("Content-Type"))
		var body map[string]any
		require.NoError(t, json.NewDecoder(r.Body).Decode(&body))
		assert.Equal(t, "http://plugin:8090", body["source"])
		require.IsType(t, map[string]any{}, body["payload"])
		w.WriteHeader(http.StatusOK)
		require.NoError(t, json.NewEncoder(w).Encode(map[string]any{"valid": true}))
	}))
	defer srv.Close()

	v := validation.NewValidator(srv.URL)
	result, err := v.Validate(context.Background(), "http://plugin:8090", map[string]any{"text": "hello"})

	require.NoError(t, err)
	assert.True(t, result.Valid)
	assert.Empty(t, result.Errors)
}

func TestValidator_InvalidPayload(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusUnprocessableEntity)
		require.NoError(t, json.NewEncoder(w).Encode(map[string]any{
			"valid":  false,
			"errors": []map[string]string{{"field": "source", "message": "field 'source' is required"}},
		}))
	}))
	defer srv.Close()

	v := validation.NewValidator(srv.URL)
	result, err := v.Validate(context.Background(), "http://plugin:8090", map[string]any{})

	require.NoError(t, err)
	assert.False(t, result.Valid)
	assert.NotEmpty(t, result.Errors)
}

func TestValidator_ServiceUnavailable(t *testing.T) {
	v := validation.NewValidator("http://localhost:1") // unreachable

	_, err := v.Validate(context.Background(), "http://plugin:8090", map[string]any{"text": "test"})
	assert.Error(t, err)
}
