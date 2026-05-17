package validation

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"
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

// NewValidator creates a Validator pointing at the given sidecar base URL.
func NewValidator(baseURL string) *Validator {
	return &Validator{
		baseURL: baseURL,
		client: &http.Client{
			Timeout: 2 * time.Second,
		},
	}
}

// Validate sends payload to the sidecar and returns the result.
func (v *Validator) Validate(ctx context.Context, payload map[string]any) (*ValidationResult, error) {
	body, err := json.Marshal(payload)
	if err != nil {
		return nil, fmt.Errorf("marshal payload: %w", err)
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

	if resp.StatusCode != http.StatusOK && resp.StatusCode != http.StatusUnprocessableEntity {
		raw, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))
		return nil, fmt.Errorf("unexpected status %d: %s", resp.StatusCode, raw)
	}

	var result ValidationResult
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return nil, fmt.Errorf("decode response: %w", err)
	}

	return &result, nil
}
