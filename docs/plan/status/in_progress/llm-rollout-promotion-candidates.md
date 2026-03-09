# LLM Rollout Promotion Candidates

Date: 2026-03-09
Branch: `plan/llm-decision-hooks`

## Initial assist candidates

- `provider-error-classifier`
  - Why: semantic ambiguity is common, user-facing outcome is recoverable, and deterministic fallback already exists.
  - Suggested mode: move from `shadow` to `assist` first.
- `auto-slash-command`
  - Why: diagnostics intent is recoverable, cached prompts are cheap, and disagreement review is straightforward.
  - Suggested mode: move from `shadow` to `assist` first.

## Observe longer before promotion

- `delegation-fallback-orchestrator`
  - Why: fallback mutation is helpful but can redirect delegation behavior.
- `pr-body-evidence-guard`
  - Why: semantic section detection is useful but still affects release workflow gates.
- `done-proof-enforcer`
  - Why: semantic evidence wording changes completion gating and should keep more shadow evidence first.

## Keep in shadow for now

- `agent-model-resolver`
  - Why: routing changes alter subagent choice and can ripple into tool surface and cost.
- `agent-denied-tool-enforcer`
  - Why: semantic mutation/tool implication decisions can block execution paths and should remain conservative.
- `validation-evidence-ledger`
  - Why: semantic validation classification can affect downstream done-proof outcomes and needs more longitudinal data.

## Promotion rule of thumb

- Promote to `assist` only after disagreement reports stay low and stable for that hook.
- Promote to `enforce` only after assist behavior is proven and deterministic fallback still exists.

## Suggested runtime config snippet

```json
{
  "llmDecisionRuntime": {
    "enabled": true,
    "mode": "shadow",
    "hookModes": {
      "auto-slash-command": "assist",
      "provider-error-classifier": "assist"
    }
  }
}
```
