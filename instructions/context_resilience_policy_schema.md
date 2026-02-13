# Context Resilience Policy Schema

Epic 11 Task 11.1 defines configuration and behavior contracts for long-session context resilience.

## Objectives

- provide deterministic truncation/pruning behavior under constrained context budgets
- preserve critical evidence needed for safe continuation
- make pruning and recovery decisions visible with configurable signal levels

## Config shape

Proposed config section:

```json
{
  "resilience": {
    "enabled": true,
    "truncation_mode": "default",
    "protected_tools": ["bash", "read", "edit", "write", "apply_patch"],
    "protected_message_kinds": ["error", "result", "decision"],
    "notification_level": "normal"
  }
}
```

Field requirements:

- `enabled`: boolean, default `true`
- `truncation_mode`: enum, one of `default` or `aggressive`
- `protected_tools`: optional list of tool ids to never prune when they contain command outcomes
- `protected_message_kinds`: optional list of semantic message categories to preserve
- `notification_level`: enum, one of `quiet`, `normal`, or `verbose`

Unknown keys should be ignored with a warning in diagnostics.

## Truncation modes

### `default`

- preserve all protected tools/messages
- prune obvious duplicates and stale superseded content
- retain at least one recent successful command outcome per active workflow

### `aggressive`

- apply `default` behavior first
- increase pruning pressure for old non-protected analysis chatter
- collapse repeated failure retries into compact summaries while preserving the latest actionable error

## Protected artifacts

Protected artifacts are never removed during pruning:

- tool results for `protected_tools` entries
- messages tagged as `protected_message_kinds`
- latest command invocation + exit outcome for each command family in session scope

If protection constraints conflict with budget limits, the system should emit a recovery warning instead of silently dropping protected evidence.

## Notification levels

### `quiet`

- notify only when resilience actions could alter execution safety

### `normal`

- notify on major pruning/recovery events and skipped actions

### `verbose`

- emit per-action diagnostics including prune reason categories and protected-preservation counts

## Validation requirements

Reject invalid config when:

- enum fields contain unsupported values
- list fields are not arrays of non-empty strings
- required booleans are non-boolean values

Diagnostics must include:

- invalid field path
- invalid value
- accepted values or shape
- remediation guidance

## Compatibility and evolution

- `truncation_mode` defaults to `default` when absent
- missing optional lists imply conservative built-in protections
- future modes/levels must remain backward compatible with current enum values

This schema is intentionally command-agnostic so Epic 11 Task 11.2 can implement pruning without changing consumer-facing config shape.
