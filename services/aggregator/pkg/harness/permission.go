package harness

import (
	"fmt"
	"slices"
)

// CheckPermission runs Stage 5: it enforces tenant-scoped access control.
//
// Policy:
//   - An empty AllowedTools slice means "allow all registered tools". This
//     preserves backwards compatibility with untasked general collection
//     where no explicit per-tenant policy has been configured.
//   - Otherwise the named tool must appear in the allow-list.
//
// The tenant ID on the Permission is not re-validated here (the caller is
// responsible for stamping it); only the tool membership is checked.
func CheckPermission(perm Permission, toolName string) error {
	if len(perm.AllowedTools) == 0 {
		return nil // allow-all (untasked / default tenant)
	}
	if slices.Contains(perm.AllowedTools, toolName) {
		return nil
	}
	return fmt.Errorf("tool %q is not permitted for tenant %q", toolName, perm.TenantID)
}
