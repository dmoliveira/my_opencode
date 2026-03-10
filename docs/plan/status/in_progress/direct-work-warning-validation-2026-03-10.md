# Direct Work Warning Validation - 2026-03-10

Branch: `wt/post-merge-parity-backlog`
Worktree: `/Users/cauhirsch/Codes/Projects/my_opencode-wt-post-merge-parity-backlog`

## Scope

Validation for the first local delegation-first direct-work discipline slice and its repeat-edit escalation follow-up.

Covered changes:

- `plugin/gateway-core/src/hooks/direct-work-warning/index.ts`
- `plugin/gateway-core/src/index.ts`
- `plugin/gateway-core/test/direct-work-warning-hook.test.mjs`

## Results

### 1. Primary-session direct edits now get a delegation-first warning

- write-like tool calls from non-child sessions receive a direct-work reminder before execution
- the reminder carries the target path when available and points the operator back toward delegation-first behavior

### 2. Delegated child sessions are not warned

- subagent child sessions linked through the delegation session map bypass the warning
- this keeps the hook focused on primary-orchestrator behavior rather than normal delegated implementation work

### 3. Repeated direct-edit blocking is available but stays opt-in

- the first primary-session direct edit warns by default
- optional repeated-edit blocking exists behind `directWorkWarning.blockRepeatedEdits`
- when enabled, the next write-like direct edit in the same session is blocked and the block resets on `session.deleted`

## Validation commands

- `npm --prefix plugin/gateway-core run build`
- `node --test plugin/gateway-core/test/direct-work-warning-hook.test.mjs`
- `npm --prefix plugin/gateway-core test`

## Summary

- Status: pass
- This slice ships as warn-first by default, with optional repeated-edit blocking available for stricter rollout
