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
  - current regenerated report shows `0` disagreements and no hook-specific signal yet

## Promotion snapshot

- Keep in `assist`:
  - `auto-slash-command`
  - `provider-error-classifier`
- Keep in `shadow` until fresh live disagreement data accumulates again:
  - `validation-evidence-ledger`
  - `delegation-fallback-orchestrator`
  - `todo-continuation-enforcer`

## Post-tuning note

- The freshly regenerated disagreement report currently shows `0` disagreements and no hook-specific pairs.
- Interpretation: there is not enough live disagreement evidence in the current window to justify a promotion decision yet, so the next step is to gather a new shadow traffic sample rather than flip modes immediately.

## Why

- Synthetic reliability is currently strong across semantic and workflow scenarios.
- Live disagreement data is the main gating signal now.
- The freshly regenerated disagreement report currently has no disagreement entries, so there is no live promotion signal to trust yet.
- `delegation-fallback-orchestrator` remains the best next promotion candidate once a new live evidence window exists.

## Immediate next step

1. Let a fresh shadow traffic window accumulate enough LLM decision audit events.
2. Regenerate `docs/plan/status/in_progress/llm-disagreement-rollout-report.md` after that window.
3. Promote `delegation-fallback-orchestrator` only when the refreshed report has enough live evidence and still stays low/stable.
