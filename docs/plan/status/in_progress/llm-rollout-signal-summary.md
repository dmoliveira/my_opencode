# LLM Rollout Signal Summary

Date: 2026-03-10
Branch: `plan/llm-decision-hooks`

## Inputs

- Semantic reliability report: `docs/plan/status/in_progress/llm-scenario-report.md`
- Workflow reliability report: `docs/plan/status/in_progress/workflow-scenario-report.md`
- Live disagreement report: `docs/plan/status/in_progress/llm-disagreement-rollout-report.md`

## Current signal

- Semantic scenarios: `11/11` passing (`100%`)
- Workflow/enforcer scenarios: `10/10` passing (`100%`)
- Live disagreement hotspots:
  - `validation-evidence-ledger`: `tune`
  - `delegation-fallback-orchestrator`: `observe`

## Promotion snapshot

- Keep in `assist`:
  - `auto-slash-command`
  - `provider-error-classifier`
- Keep in `shadow` and continue tuning:
  - `validation-evidence-ledger`
- Keep in `shadow`, but it is the next likely promotion candidate once more live traffic confirms stability:
  - `delegation-fallback-orchestrator`

## Why

- Synthetic reliability is currently strong across semantic and workflow scenarios.
- Live disagreement data is the main gating signal now.
- `validation-evidence-ledger` still disagrees often enough to justify more tuning before promotion.
- `delegation-fallback-orchestrator` has lower disagreement volume and remains the best next candidate for `assist` after more telemetry.

## Immediate next step

1. Let more real assist traffic accumulate.
2. Regenerate `docs/plan/status/in_progress/llm-disagreement-rollout-report.md`.
3. Promote `delegation-fallback-orchestrator` only if disagreement stays low/stable.
