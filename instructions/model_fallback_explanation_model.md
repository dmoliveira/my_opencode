# Provider/Model Fallback Explanation Model

Epic 12 Task 12.1 defines the trace contract for explaining model and provider fallback decisions.

## Goals

- make every routing decision explainable in deterministic order
- keep default output readable while preserving deep diagnostics for debugging
- avoid exposing secrets or sensitive provider identifiers in normal traces

## Trace structure

A trace represents one routing decision in three stages:

1. `requested`: what the caller asked for
2. `attempted`: ordered candidates that were evaluated
3. `selected`: final model/provider outcome

Reference shape:

```json
{
  "requested": {
    "category": "deep",
    "model": "openai/gpt-5.3-codex",
    "source": "user_override"
  },
  "attempted": [
    {
      "rank": 1,
      "model": "openai/gpt-5.3-codex",
      "provider": "openai",
      "result": "unavailable",
      "reason": "model_not_in_available_set"
    },
    {
      "rank": 2,
      "model": "openai/gpt-5-mini",
      "provider": "openai",
      "result": "accepted",
      "reason": "category_default_fallback"
    }
  ],
  "selected": {
    "model": "openai/gpt-5-mini",
    "provider": "openai",
    "reason": "fallback_unavailable_model_to_category"
  }
}
```

## Output levels

### Compact (default)

- include only `requested.model/category`, final `selected`, and 1-line fallback reason
- include attempted count but not full per-attempt details
- optimized for `/routing status` and routine debugging

### Verbose

- include full `attempted` chain with rank and rejection reason per candidate
- include resolution source metadata (`system_default`, `category_default`, `user_override`)
- include deterministic timestamps or sequence ids when available

## Redaction rules

Always redact in both compact and verbose modes:

- API keys, tokens, bearer strings, authorization headers
- full endpoint query strings containing credentials
- account-scoped identifiers that can reveal tenant internals

Redaction behavior:

- preserve structural placeholders (`***redacted***`) so traces remain parseable
- keep provider class labels (`openai`, `anthropic`, etc.) unless explicitly marked sensitive
- if a field is fully sensitive, replace value and attach a redaction reason code

## Determinism requirements

- attempted candidates must be listed in exact evaluation order
- fallback reason codes must use stable identifiers (no free-form prose)
- identical inputs and availability state must yield identical trace output

## Integration targets

Task 12.2 should emit this trace model from runtime routing.
Task 12.3 should expose compact and verbose views via user-facing commands.
Task 12.4 should verify deterministic traces and redaction safety.
