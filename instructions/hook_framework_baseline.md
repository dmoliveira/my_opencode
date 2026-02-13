# Hook Framework Baseline

This document defines the initial event + config model for Epic 4 Task 4.1.

## Supported events

- `PreToolUse`: before executing a tool or shell command
- `PostToolUse`: after a tool or shell command completes
- `Stop`: when a turn/session is ending

## Config shape

`hooks` section (optional):

```json
{
  "hooks": {
    "enabled": false,
    "disabled": ["hook-id"],
    "order": ["hook-id-a", "hook-id-b"]
  }
}
```

- `enabled`: global on/off flag for hook execution
- `disabled`: per-hook denylist by id
- `order`: explicit precedence list (first id executes first)

## Deterministic planning order

For each event, execution order is stable and deterministic:

1. explicit `hooks.order` precedence
2. ascending numeric hook `priority`
3. lexicographic `hook_id` tie-break

This baseline intentionally does not enable any default hook actions.
Concrete hooks are introduced in Task 4.2.
