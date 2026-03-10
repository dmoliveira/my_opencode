# Todo Continuation Rollout Decision - 2026-03-10

## Decision

Keep `todo-continuation-enforcer` in `shadow` for now.

## Why

- mainline already contains the LLM-assisted mixed-signal continuation path, so no duplicate implementation is needed
- synthetic and workflow evidence is strong, including the mixed-signal case
- live disagreement evidence does not yet include a meaningful `todo-continuation-enforcer` traffic window, so there is not enough production-style signal to justify promotion to `assist`

## Evidence checked

- live config keeps `todo-continuation-enforcer` in shadow: `.opencode/gateway-core.config.json`
- implementation exists on main: `plugin/gateway-core/src/hooks/todo-continuation-enforcer/index.ts`
- targeted tests exist on main: `plugin/gateway-core/test/todo-continuation-enforcer-hook.test.mjs`
- workflow scenarios pass 14/14 for this hook: `docs/plan/status/in_progress/workflow-scenario-report.md`
- disagreement report currently lists only `validation-evidence-ledger` and `delegation-fallback-orchestrator`: `docs/plan/status/in_progress/llm-disagreement-rollout-report.md`

## Conflict check

- there is no conflict with the other session's implementation work because the LLM decision path is already present on `main`
- the remaining work is rollout governance only: gather fresh live telemetry, regenerate disagreement reporting, then revisit promotion

## Next trigger to reopen

Promote only after all are true:

- fresh disagreement report includes meaningful `todo-continuation-enforcer` live samples
- disagreement remains low/stable over that window
- no false-positive autonomous follow-on execution is observed in operator review
