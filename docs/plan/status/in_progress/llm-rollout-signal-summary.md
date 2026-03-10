# LLM Rollout Signal Summary

Date: 2026-03-10
Branch: `fix/next-parity-item-2`

## Inputs

- Semantic reliability report: `docs/plan/status/in_progress/llm-scenario-report.md`
- Workflow reliability report: `docs/plan/status/in_progress/workflow-scenario-report.md`
- Live disagreement report: `docs/plan/status/in_progress/llm-disagreement-rollout-report.md`

## Current signal

- Semantic scenarios: `11/11` passing (`100%`)
- Workflow/enforcer scenarios: `16/16` passing (`100%`)
- Live disagreement hotspots:
  - `validation-evidence-ledger`: `tune`
  - `delegation-fallback-orchestrator`: `observe`

## Promotion snapshot

- Keep in `assist`:
  - `auto-slash-command`
  - `provider-error-classifier`
- Keep in `shadow` and continue tuning:
  - `validation-evidence-ledger`
- Keep in `shadow`, but it is still the next likely promotion candidate once a fresh disagreement window confirms stability:
  - `delegation-fallback-orchestrator`

## Post-tuning note

- After improving deterministic wrapped-test matching for `validation-evidence-ledger`, the checked-in disagreement snapshot still shows the historical `not_validation -> test` pair.
- Interpretation: the current report still reflects previously collected audit events; a fresh traffic window is needed before changing the promotion recommendation.

## Why

- Synthetic reliability is currently strong across semantic and workflow scenarios.
- Live disagreement data is the main gating signal now.
- `validation-evidence-ledger` still disagrees often enough to justify more tuning before promotion.
- `delegation-fallback-orchestrator` remains the best next promotion candidate, but the checked-in disagreement report still recommends observation rather than a live assist flip.

## Immediate next step

1. Regenerate `docs/plan/status/in_progress/llm-disagreement-rollout-report.md` after a fresh shadow traffic window.
2. Promote `delegation-fallback-orchestrator` only if the refreshed disagreement report still stays low/stable.
3. Keep `validation-evidence-ledger` and `todo-continuation-enforcer` in shadow until their live disagreement signals improve.
