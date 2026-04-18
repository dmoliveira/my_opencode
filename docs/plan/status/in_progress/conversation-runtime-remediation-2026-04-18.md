# Conversation Runtime Remediation - 2026-04-18

Branch lineage for this work:

- `feat/conversation-recovery-hardening`

## Goal

Reduce the last high-friction runtime failures seen in recent SQLite conversation history:

1. sessions that appear stuck until the user manually says `continue`
2. protected-branch / primary-worktree guard false positives that block safe coordination work
3. dependency-guard flows that stay blocked even after manual review
4. weak runtime observability for recovery vs. blocker outcomes

## Evidence From SQLite Review

- Repeated user rescue nudges across the last 5 days, including variants of:
  - `looks like you got stuck`
  - `continue as you got stuck`
  - `comeback from where you got stuck`
- PR and shell coordination work blocked by guardrails even when the work was non-destructive:
  - `gh pr create` / PR-flow completion
  - harmless repo inspection such as `git remote -v`
  - maintenance-helper routing loops on protected branches
- Dependency work (notably Playwright install flow) blocked repeatedly after manual package review, forcing fallback audits instead of a clean approved retry path.
- Hook audit visibility is currently easy to miss because the local audit file is opt-in and not surfaced in the user-facing remediation loop.

## Scope

### Doing

- [ ] Add stronger stuck-session recovery for completed progress-promising assistant tails that go idle without follow-through.
- [ ] Record manual rescue phrasing as an explicit recovery signal for later tuning.
- [ ] Allow safe protected-branch coordination commands (`git remote -v`, PR creation/comment flows, maintenance-helper invocations).
- [ ] Add an explicit dependency-review override path with audit logging instead of a binary permanent block.
- [ ] Improve operator-facing observability/docs for gateway event audit output.

### Out of scope for this slice

- [ ] Full transcript/UI role redesign for synthetic hook messages in the host application.
- [ ] Broad GitHub API mutation allowlisting beyond the narrow PR/coordination cases backed by observed failures.

## Candidate Files

- `plugin/gateway-core/src/hooks/session-recovery/index.ts`
- `plugin/gateway-core/src/hooks/todo-continuation-enforcer/index.ts`
- `plugin/gateway-core/src/hooks/protected-shell-policy.ts`
- `plugin/gateway-core/src/hooks/dependency-risk-guard/index.ts`
- `plugin/gateway-core/src/audit/event-audit.ts`
- `plugin/gateway-core/test/session-recovery-hook.test.mjs`
- `plugin/gateway-core/test/workflow-conformance-guard-hook.test.mjs`
- `plugin/gateway-core/test/dependency-risk-guard-hook.test.mjs`
- `docs/readme-deep-notes.md`

## Validation Plan

1. Focused gateway hook tests for recovery, workflow guard, and dependency guard.
2. Plugin build so test imports read the updated `dist/` output.
3. Final reviewer/verifier pass after implementation stabilizes.

## Success Criteria

- idle sessions recover more often without user rescue nudges
- safe PR/coordination commands stop bouncing through false-positive guard blocks
- dependency installs can proceed after explicit manual review acknowledgment
- audit output clearly records whether a recovery or override was injected
