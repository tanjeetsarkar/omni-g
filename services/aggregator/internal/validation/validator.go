package validation

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"

	"github.com/rs/zerolog/log"
)

// ErrorDetail is a single structured validation error from the sidecar.
type ErrorDetail struct {
	Field   string `json:"field"`
	Message string `json:"message"`
}

// ValidationResult is returned by the validation sidecar.
type ValidationResult struct {
	Valid  bool          `json:"valid"`
	Errors []ErrorDetail `json:"errors,omitempty"`
}

// Validator delegates schema validation to the Python sidecar.
type Validator struct {
	client  *http.Client
	baseURL string
}

type validateRequest struct {
	Source  string         `json:"source"`
	Payload map[string]any `json:"payload"`
}

// NewValidator creates a Validator pointing at the given sidecar base URL.
func NewValidator(baseURL string) *Validator {
	return &Validator{
		baseURL: baseURL,
		client: &http.Client{
			Timeout: 5 * time.Second,
		},
	}
}

// Validate sends the source+payload envelope to the sidecar and returns the result.
func (v *Validator) Validate(ctx context.Context, source string, payload map[string]any) (*ValidationResult, error) {
	logger := log.With().Str("source", source).Logger()

	body, err := json.Marshal(validateRequest{Source: source, Payload: payload})
	if err != nil {
		return nil, fmt.Errorf("marshal validate request: %w", err)
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, v.baseURL+"/validate", bytes.NewReader(body))
	if err != nil {
		return nil, fmt.Errorf("build request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := v.client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("call validation service: %w", err)
	}
	defer resp.Body.Close()

	rawBody, err := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if err != nil {
		return nil, fmt.Errorf("read validation response: %w", err)
	}

	if resp.StatusCode != http.StatusOK && resp.StatusCode != http.StatusUnprocessableEntity {
		if len(rawBody) > 4096 {
			rawBody = rawBody[:4096]
		}
		return nil, fmt.Errorf("unexpected status %d: %s", resp.StatusCode, rawBody)
	}

	var result ValidationResult
	if err := json.Unmarshal(rawBody, &result); err != nil {
		return nil, fmt.Errorf("decode response: %w", err)
	}

	logger.Debug().Bool("valid", result.Valid).Int("error_count", len(result.Errors)).Msg("validation completed")

	return &result, nil
}
