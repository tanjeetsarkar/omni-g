package agent

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"
)

// openRouterMessage is a chat message for the OpenRouter API.
type openRouterMessage struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

// openRouterRequest is the request body for OpenRouter chat completions.
type openRouterRequest struct {
	Model    string              `json:"model"`
	Messages []openRouterMessage `json:"messages"`
	Stream   bool                `json:"stream"`
}

// openRouterResponse is the response from OpenRouter chat completions.
type openRouterResponse struct {
	Choices []struct {
		Message struct {
			Content string `json:"content"`
		} `json:"message"`
	} `json:"choices"`
	Error *struct {
		Message string `json:"message"`
		Code    int    `json:"code"`
	} `json:"error,omitempty"`
}

// openRouterBaseURL is the OpenRouter API endpoint.
const openRouterBaseURL = "https://openrouter.ai/api/v1/chat/completions"

// callOpenRouter sends a chat completion request to OpenRouter and returns
// the response content.
func callOpenRouter(
	ctx context.Context,
	apiKey string,
	model string,
	messages []openRouterMessage,
	timeout time.Duration,
) (string, error) {
	reqBody := openRouterRequest{
		Model:    model,
		Messages: messages,
		Stream:   false,
	}

	body, err := json.Marshal(reqBody)
	if err != nil {
		return "", fmt.Errorf("marshal request: %w", err)
	}

	httpReq, err := http.NewRequestWithContext(ctx, http.MethodPost, openRouterBaseURL, bytes.NewReader(body))
	if err != nil {
		return "", fmt.Errorf("create request: %w", err)
	}
	httpReq.Header.Set("Content-Type", "application/json")
	httpReq.Header.Set("Authorization", "Bearer "+apiKey)
	httpReq.Header.Set("HTTP-Referer", "https://github.com/omni-g/aggregator")
	httpReq.Header.Set("X-Title", "Omni-G Aggregator")

	client := &http.Client{Timeout: timeout}
	resp, err := client.Do(httpReq)
	if err != nil {
		return "", fmt.Errorf("http request: %w", err)
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", fmt.Errorf("read response: %w", err)
	}

	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("openrouter returned %d: %s", resp.StatusCode, string(respBody))
	}

	var result openRouterResponse
	if err := json.Unmarshal(respBody, &result); err != nil {
		return "", fmt.Errorf("unmarshal response: %w", err)
	}

	if result.Error != nil {
		return "", fmt.Errorf("openrouter error %d: %s", result.Error.Code, result.Error.Message)
	}

	if len(result.Choices) == 0 {
		return "", fmt.Errorf("openrouter returned no choices")
	}

	return result.Choices[0].Message.Content, nil
}
