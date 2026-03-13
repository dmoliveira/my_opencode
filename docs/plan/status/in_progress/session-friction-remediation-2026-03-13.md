# Session Friction Remediation - 2026-03-13

Branch lineage for this work:

- `feat/session-friction-remediation-20260313`

## Goal

Reduce the cases where OpenCode feels stuck by closing four gaps seen in today's session review:

1. delegated `task` failures that never turn into a parent fallback reply
2. long tool-only turns with no user-visible progress pulse
3. protected-`main` maintenance tasks that bounce back to the user instead of moving to a safe worktree path
4. stuck-session diagnostics that miss silent parent-turn failures after delegated aborts

## Evidence From Today

- `/doctor` session `ses_31b6e8732ffejQC2pBERb71Ljd` stalled after a delegated child `task` failed with `Tool execution aborted` and no parent fallback text landed.
- Cleanup session `ses_31bf65bf7ffeWUQ0OTNrHzo9HL` required repeated `yes` turns for safe-next-step repo maintenance.
- Five of six top-level non-classifier sessions took more than 30 seconds before the first visible assistant text.

## Scope

### Doing

- [ ] Decide whether delegated abort handling should stay hook-local or move into a shared parent-turn recovery helper.
- [ ] Decide whether protected-`main` remediation should remain advisory in this slice or gain a real helper command next.
- [ ] Decide whether progress heartbeat should stay wall-clock-driven or also count tool-only steps.

### Done

- [x] Reviewed today's runtime DB sessions and isolated the main user-friction patterns.
- [x] Confirmed the current gaps in `delegate-task-retry`, `session-recovery`, `long-turn-watchdog`, and `scripts/session_command.py`.
- [x] Created dedicated worktree branch `feat/session-friction-remediation-20260313`.
- [x] Added delegated-task abort detection and fallback guidance beyond argument-shape errors.
- [x] Added shared parent-turn recovery injection for delegated task aborts.
- [x] Added a user-visible long-turn progress heartbeat for tool-only turns.
- [x] Added repeated tool-call threshold support for long-turn heartbeats.
- [x] Added a safe maintenance-worktree remediation hint for protected `main` bash blocks.
- [x] Added a real `scripts/worktree_helper_command.py maintenance` helper path for protected-`main` maintenance suggestions.
- [x] Extended runtime stuck-session diagnostics to catch silent parent failures after delegated aborts.
- [x] Added regression coverage for delegate retry, long-turn heartbeat, workflow guard remediation messaging, and session-doctor abort detection.
- [x] Ran targeted gateway hook tests plus a focused session-doctor fixture validation.
- [x] Verified Python syntax with `python3 -m py_compile`.
- [x] Ran reviewer pass and fixed the blocking issues it found before merge.

## Validation Notes

- `node --test plugin/gateway-core/test/delegate-task-retry-hook.test.mjs plugin/gateway-core/test/long-turn-watchdog-hook.test.mjs plugin/gateway-core/test/workflow-conformance-guard-hook.test.mjs` -> pass
- `node --test plugin/gateway-core/test/delegate-task-retry-hook.test.mjs plugin/gateway-core/test/long-turn-watchdog-hook.test.mjs plugin/gateway-core/test/workflow-conformance-guard-hook.test.mjs plugin/gateway-core/test/session-recovery-hook.test.mjs` -> pass
- focused rerun: `node --test plugin/gateway-core/test/long-turn-watchdog-hook.test.mjs plugin/gateway-core/test/workflow-conformance-guard-hook.test.mjs plugin/gateway-core/test/session-recovery-hook.test.mjs` -> pass
- Focused `session_command.py doctor --json` fixture run -> detected `silent_parent_after_delegation_abort` as expected
- `python3 -m py_compile scripts/session_command.py scripts/selftest.py scripts/worktree_helper_command.py` -> pass
- `python3 scripts/worktree_helper_command.py maintenance --directory /Users/cauhirsch/Codes/Projects/my_opencode --command "git branch -D feature/test" --json` -> pass
- `npm --prefix plugin/gateway-core run build` is currently blocked by pre-existing TypeScript environment issues in this checkout (`node:` module typings / `@types/node` resolution), so targeted tests were run against the existing dist output after syncing the relevant files

## Implementation Order

### 1. Delegation failure fallback

- Expand `plugin/gateway-core/src/hooks/delegate-task-retry/index.ts` to recognize generic delegated abort output such as `Tool execution aborted`.
- Decide whether the hook should:
  - append retry-now guidance only, or
  - trigger a structured fallback signal that parent-turn handling can surface immediately.
- Add tests for generic aborts and make sure known argument-error behavior still passes.

### 2. Long-turn progress heartbeat

- Audit whether `long-turn-watchdog` should stay as a warning-only hook or become a progress-pulse source.
- Preferred direction: append a short progress pulse after a configurable threshold and after repeated tool-only steps.
- Keep the message lightweight so it reassures the user without spamming the turn.

### 3. Protected-main maintenance remediation

- Identify the best interception point for safe repo-maintenance tasks that fail on protected `main`.
- Preferred direction: emit a deterministic remediation recipe that creates a throwaway worktree and continues from there.
- If full auto-creation is too invasive for one slice, land a first version that standardizes the fallback and removes yes/no churn.

### 4. Session doctor coverage

- Extend `scripts/session_command.py` stuck-session scan to flag:
  - parent sessions whose last assistant turn is incomplete
  - last part is a `task` tool
  - child session failed or completed
  - no trailing parent text was produced
- Bubble this into `/session doctor` and the unified doctor output.

### 5. Validation

- Add targeted hook/unit coverage first.
- Then run the smallest doctor/session selftests that cover delegated recovery and stuck-session diagnostics.
- End with one narrow integration path that proves the parent surfaces a fallback instead of going silent.

## Candidate Files

- `plugin/gateway-core/src/hooks/delegate-task-retry/index.ts`
- `plugin/gateway-core/src/hooks/long-turn-watchdog/index.ts`
- `plugin/gateway-core/src/hooks/session-recovery/index.ts`
- `plugin/gateway-core/src/index.ts`
- `scripts/session_command.py`
- `scripts/doctor_command.py`
- `scripts/selftest.py`
- `plugin/gateway-core/test/delegate-task-retry-hook.test.mjs`

## Open Decisions

- Whether delegated abort handling belongs entirely in `delegate-task-retry` or should route through a shared parent-turn recovery helper.
- Whether the protected-`main` fix should be advisory only in this slice or include a real auto-worktree helper command.
- Whether progress heartbeat should trigger by wall-clock only, tool-step count only, or both.
