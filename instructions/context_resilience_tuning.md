# Context Resilience Tuning Guide

Use this guide to tune long-session stability when context budgets become tight.

## Baseline profile

Recommended defaults for most sessions:

```json
{
  "resilience": {
    "enabled": true,
    "truncation_mode": "default",
    "notification_level": "normal",
    "protected_tools": ["bash", "read", "edit", "write", "apply_patch"],
    "protected_message_kinds": ["error", "result", "decision"]
  }
}
```

## When to use `aggressive`

Move to `aggressive` when:

- sessions repeatedly hit context limits
- analysis chatter grows faster than actionable outputs
- you need stronger trimming before recovery behavior degrades

Keep `notification_level` at `verbose` while tuning so pruning reasons are easy to audit.

## Protection strategy

- Keep command-producing tools in `protected_tools` to avoid losing execution evidence.
- Keep at least one intent-bearing semantic kind (for example `decision`) in `protected_message_kinds`.
- Avoid over-protecting broad kinds in constrained sessions; excessive protection can block budget trimming.

## Operational workflow

1. Run `/resilience status --json` to verify effective policy.
2. Run `/resilience doctor --json` to validate stress behavior and recovery readiness.
3. If diagnostics show low drop counts but high context pressure, tighten to `aggressive`.
4. If diagnostics show fallback-heavy behavior, loosen protections only after preserving command outcomes.

## Anti-patterns

- `enabled=false` during long debugging sessions with heavy tool output.
- Protecting every message kind, which prevents useful pruning.
- Using `quiet` notification while actively changing pruning policy.
