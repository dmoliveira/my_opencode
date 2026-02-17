# Autopilot Hook Roadmap 🚀

This document defines the migration from script-driven `/autopilot` to a plugin hook loop with idle-time auto-injection.

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

Canonical command surface:

- `/autopilot*` commands are the only loop controls.
- Ralph compatibility aliases were removed to simplify command routing and hook injection.

Config wiring target (optional, requires bun runtime):

- plugin spec entry in `opencode.json`: `file:{env:HOME}/.config/opencode/my_opencode/plugin/autopilot-loop`
- keep disabled by default until host can install `file:` plugins via bun.

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
   - Current status: command bridge now auto-cleans stale orphan loop state during `/autopilot status`, `/autopilot report`, `/autopilot go`, `/gateway status`, and `/gateway doctor`; `/autopilot*` now emits deterministic runtime routing mode (`plugin_gateway` vs `python_command_bridge`) with bun-aware fallback.

5. **Deprecation path**
   - Mark script loop execution path deprecated after hook stability window.

## Safety rules

- Never auto-inject past max iteration limit.
- Never auto-finish without completion signal for `promise` mode.
- Deactivate loops when completion token is repeatedly emitted but runtime remains `running` with blockers, to avoid infinite idle reinjection.
  - default behavior now stops on the first contradictory cycle (`maxIgnoredCompletionCycles=1`), configurable via gateway autopilot loop config.
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
