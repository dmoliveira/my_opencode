# Autopilot Hook Roadmap 🚀

This document defines the migration from script-driven `/autopilot` to a plugin hook loop with idle-time auto-injection (ralph-loop style).

## Why this migration matters

- Script-only flow can pause after a cycle and rely on explicit resume commands.
- Hook-based flow can continue automatically on `session.idle` until completion.
- We keep `/autopilot` command compatibility while upgrading backend behavior.

## Target behavior (parity goal)

- Event-driven loop state bound to a session.
- Idle event checks completion and injects continuation prompt when needed.
- Hard stop conditions: completion reached, max iterations reached, manual cancel.
- Completion modes:
  - `promise` (default): requires `<promise>DONE</promise>`
  - `objective` (optional): requires objective completion marker

## Current scaffold delivered

TypeScript scaffold is added at `plugin/autopilot-loop/`:

- `plugin/autopilot-loop/src/index.ts` - hook entrypoint + lifecycle logic
- `plugin/autopilot-loop/src/storage.ts` - persisted state read/write/clear/increment
- `plugin/autopilot-loop/src/detector.ts` - completion signal detection
- `plugin/autopilot-loop/src/injector.ts` - continuation prompt builder
- `plugin/autopilot-loop/src/types.ts` - typed API contracts
- `plugin/autopilot-loop/src/constants.ts` - stable defaults
- `plugin/autopilot-loop/package.json` + lint/format/build tooling

Command aliases now available:

- `/ralph-loop "task"` -> promise-mode `/autopilot` run
- `/cancel-ralph` -> stop active run

Config wiring target:

- plugin spec entry in `opencode.json`: `file:{env:HOME}/.config/opencode/my_opencode/plugin/autopilot-loop`

## Migration phases

1. **Scaffold (done)**
   - Introduce typed hook module with storage, detector, injector.

2. **Plugin integration**
   - Register `autopilot-loop` hook in plugin runtime event handlers.
   - Wire `event` handler for `session.idle`, `session.deleted`, `session.error`.

3. **Command bridge**
   - `/autopilot` commands start/cancel/query hook state (instead of script loop progression).
   - Preserve existing command names and JSON contract.

4. **Guardrails parity**
   - Keep scope/budget/reason-code behavior aligned.
   - Add kill-switch and orphan-state cleanup.

5. **Deprecation path**
   - Mark script loop execution path deprecated after hook stability window.

## Safety rules

- Never auto-inject past max iteration limit.
- Never auto-finish without completion signal for `promise` mode.
- Always allow manual `/autopilot stop`.
- Emit clear reason codes for every terminal state.

## Validation checklist

- Unit tests for detector/storage/injector.
- Integration tests for `session.idle` auto-injection.
- E2E tests for:
  - promise completion
  - objective completion
  - max-iteration stop
  - cancel flow
