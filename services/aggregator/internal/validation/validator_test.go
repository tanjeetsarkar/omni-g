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
		w.WriteHeader(http.StatusOK)
		json.NewEncoder(w).Encode(map[string]any{"valid": true})
	}))
	defer srv.Close()

	v := validation.NewValidator(srv.URL)
	result, err := v.Validate(context.Background(), map[string]any{"text": "hello"})

	require.NoError(t, err)
	assert.True(t, result.Valid)
	assert.Empty(t, result.Errors)
}

func TestValidator_InvalidPayload(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusUnprocessableEntity)
		json.NewEncoder(w).Encode(map[string]any{
			"valid":  false,
			"errors": []map[string]string{{"field": "source", "message": "field 'source' is required"}},
		})
	}))
	defer srv.Close()

	v := validation.NewValidator(srv.URL)
	result, err := v.Validate(context.Background(), map[string]any{})

	require.NoError(t, err)
	assert.False(t, result.Valid)
	assert.NotEmpty(t, result.Errors)
}

func TestValidator_ServiceUnavailable(t *testing.T) {
	v := validation.NewValidator("http://localhost:1") // unreachable

	_, err := v.Validate(context.Background(), map[string]any{"text": "test"})
	assert.Error(t, err)
}
