# Claude-Code-Hooks Decision - 2026-03-11

Branch: `wt/claude-hooks-decision`
Worktree: `/Users/cauhirsch/Codes/Projects/my_opencode-wt-claude-hooks-decision`

## Decision

Keep `claude-code-hooks` as an intentional divergence for now.

## Why

- local runtime already has a canonical gateway-core hook pipeline for chat, tool, system-transform, and session behaviors
- upstream `claude-code-hooks` is primarily a compatibility layer for Claude-session-specific event wiring, not a unique policy capability that is missing locally
- adding a second compatibility layer now would duplicate surfaces the local gateway already owns and would likely increase maintenance cost faster than parity value

## Upstream evidence

- upstream compatibility entrypoint fans out Claude-specific handlers for chat, tool before/after, compaction, and session events in `src/hooks/claude-code-hooks/claude-code-hooks-hook.ts`
- upstream transform hook creation wires it as a distinct optional compatibility hook in `src/plugin/hooks/create-transform-hooks.ts`

## Local evidence

- divergence is already documented in `docs/upstream-divergence-registry.md`
- local gateway-core already owns the same broad event surface through its own canonical hooks and dispatch pipeline under `plugin/gateway-core/src/index.ts`

## Reopen criteria

Open a compatibility epic only if at least one becomes true:

- you need direct Claude transcript/session semantics for imported workflows
- upstream-only Claude handlers become the source of a user-visible behavior gap that gateway-core cannot express cleanly
- operators need drop-in compatibility with upstream plugin configs or event expectations

## If reopened later

Preferred first slice:

1. map upstream handler responsibilities one by one against gateway-core ownership
2. implement only missing compatibility shims, not a parallel full hook stack
3. keep gateway-core as the single canonical runtime and treat Claude compatibility as an adapter layer
