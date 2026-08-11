package harness

import (
	"encoding/json"
	"errors"
	"fmt"
	"strings"
)

// ValidateDescriptor runs Stage 1 checks on a tool descriptor before it enters
// the registry. It returns a descriptive error naming the first violation.
func ValidateDescriptor(d ToolDescriptor) error {
	if strings.TrimSpace(d.Name) == "" {
		return errors.New("tool name is required")
	}
	if d.Risk != RiskLow && d.Risk != RiskMedium && d.Risk != RiskHigh {
		return fmt.Errorf("tool %q: risk level must be low|medium|high, got %q", d.Name, d.Risk)
	}
	if len(d.InputSchema) > 0 {
		var schema map[string]any
		if err := json.Unmarshal(d.InputSchema, &schema); err != nil {
			return fmt.Errorf("tool %q: inputSchema is not valid JSON: %w", d.Name, err)
		}
		if t, ok := schema["type"].(string); ok && t != "object" {
			// MCP tool input schemas are conventionally objects; we accept
			// any parseable JSON but warn on non-object top-level types.
			return fmt.Errorf("tool %q: inputSchema top-level type should be object, got %q", d.Name, t)
		}
	}
	return nil
}

// ValidateArguments runs Stage 4 checks: it verifies that every required
// parameter declared in the tool's inputSchema is present in args with a
// non-empty value, and that present arguments match their declared types.
//
// The check is intentionally lightweight (type + required only) so the harness
// does not take a heavy JSON-schema dependency. Full draft-07 validation is
// out of scope for the V4 Phase 1 governance boundary.
func ValidateArguments(d ToolDescriptor, args map[string]any) error {
	if len(d.InputSchema) == 0 {
		return nil // no schema → nothing to validate
	}
	var schema struct {
		Required   []string       `json:"required"`
		Properties map[string]any `json:"properties"`
		Type       string         `json:"type"`
	}
	if err := json.Unmarshal(d.InputSchema, &schema); err != nil {
		return fmt.Errorf("tool %q: cannot parse inputSchema: %w", d.Name, err)
	}

	// Required fields must be present and non-empty.
	for _, field := range schema.Required {
		v, ok := args[field]
		if !ok {
			return fmt.Errorf("tool %q: missing required argument %q", d.Name, field)
		}
		if isEmpty(v) {
			return fmt.Errorf("tool %q: required argument %q is empty", d.Name, field)
		}
	}

	// Type checks for present arguments that declare a type.
	for name, val := range args {
		prop, ok := schema.Properties[name].(map[string]any)
		if !ok {
			continue
		}
		declared, _ := prop["type"].(string)
		if err := checkType(d.Name, name, declared, val); err != nil {
			return err
		}
	}
	return nil
}

// isEmpty reports whether a JSON value should be treated as "missing" for
// required-field purposes: nil, empty string, empty array, empty object.
func isEmpty(v any) bool {
	switch t := v.(type) {
	case nil:
		return true
	case string:
		return strings.TrimSpace(t) == ""
	case []any:
		return len(t) == 0
	case map[string]any:
		return len(t) == 0
	default:
		return false
	}
}

// checkType verifies a single argument value matches its declared JSON-schema type.
func checkType(toolName, field, declared string, val any) error {
	switch declared {
	case "", "any":
		return nil
	case "string":
		if _, ok := val.(string); !ok {
			return fmt.Errorf("tool %q: argument %q must be string, got %T", toolName, field, val)
		}
	case "number", "integer":
		if !isNumber(val) {
			return fmt.Errorf("tool %q: argument %q must be %s, got %T", toolName, field, declared, val)
		}
	case "boolean":
		if _, ok := val.(bool); !ok {
			return fmt.Errorf("tool %q: argument %q must be boolean, got %T", toolName, field, val)
		}
	case "object":
		if _, ok := val.(map[string]any); !ok {
			return fmt.Errorf("tool %q: argument %q must be object, got %T", toolName, field, val)
		}
	case "array":
		if _, ok := val.([]any); !ok {
			return fmt.Errorf("tool %q: argument %q must be array, got %T", toolName, field, val)
		}
	}
	return nil
}

func isNumber(v any) bool {
	switch v.(type) {
	case float32, float64, int, int32, int64, uint, uint32, uint64:
		return true
	default:
		return false
	}
}
