# Parity Hardening Validation - 2026-03-10

Branch: `wt/parity-gap-fixes`
Worktree: `/Users/cauhirsch/Codes/Projects/my_opencode-wt-parity-gap-fixes`

## Scope

Validation for the parity-hardening follow-up that fixes crossed LLM decision runtime hook bindings and adds safe hook creation/fault isolation in `plugin/gateway-core`.

Covered changes:

- `plugin/gateway-core/src/index.ts`
- `plugin/gateway-core/src/hooks/shared/safe-create-hook.ts`
- `plugin/gateway-core/test/index-bindings.test.mjs`
- `plugin/gateway-core/test/safe-create-hook.test.mjs`
- parity tracking docs under `docs/plan/` and `docs/upstream-divergence-registry.md`

## Results

### 1. LLM hook binding map

Observed:

- exported binding map now pins each LLM-assisted hook to its own hook id
- `agent-denied-tool-enforcer`, `agent-model-resolver`, `delegation-fallback-orchestrator`, `validation-evidence-ledger`, `auto-slash-command`, `provider-error-classifier`, `done-proof-enforcer`, and `pr-body-evidence-guard` all resolve through the intended ids
- regression coverage exists in `plugin/gateway-core/test/index-bindings.test.mjs`

Outcome:

- per-hook assist/shadow/enforce config can target the intended hook again

### 2. Safe hook creation path

Observed:

- `safeCreateHook` catches factory failures, records `hook_creation_failed`, and returns `null`
- `configuredHooks()` now wraps hook creation through the safe path and filters failed hooks from the final ordered list
- `stop-continuation-guard` and `keyword-detector` fall back to local no-op stubs so dependent hooks still initialize safely
- regression coverage exists in `plugin/gateway-core/test/safe-create-hook.test.mjs`

Outcome:

- a single hook init failure degrades locally instead of crashing the gateway startup path

### 3. Docs alignment

Observed:

- parity plan now lists the hardening slice explicitly
- divergence registry clarifies that `atlas` planning coverage does not imply Atlas runtime injection parity
- divergence registry keeps `claude-code-hooks` as an explicit intentional divergence

Outcome:

- parity claims now better match actual implemented scope

## Validation commands

- `npm --prefix plugin/gateway-core ci --yes`
- `npm --prefix plugin/gateway-core test`
- `npx prettier --check "src/index.ts" "src/hooks/shared/safe-create-hook.ts" "test/index-bindings.test.mjs" "test/safe-create-hook.test.mjs"`

## Summary

- Status: pass
- No blocker regressions found in the hardening slice after dependency install and test execution
