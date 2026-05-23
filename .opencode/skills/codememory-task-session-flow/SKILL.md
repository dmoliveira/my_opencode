---
name: codememory-task-session-flow
description: Use when Codememory task creation, session attach, durable memory capture, resume, or closeout flow is needed for meaningful work.
---

## Goal
Keep meaningful work attached to the right Codememory task and session so another AI can resume safely.

## Use When
- a new meaningful task needs tracking
- a worktree needs a fresh Codememory session
- durable decisions, blockers, or handoff context must be captured
- the task is being resumed or closed out

## Do Not Use When
- the request is trivial and fully answerable without durable execution
- GitHub state alone is enough and no internal handoff value exists
- the task is only about runtime SQLite inspection

## First Steps
- `oc current`
- `oc next --scope dmoliveira/my_opencode --limit 5`
- create or attach the right `task`
- create one active `session` for the active worktree

## Working Rules
- Use one active session per active worktree path.
- Attach meaningful work to a task before implementation continues.
- Record only durable blockers, decisions, conventions, and handoff context.
- Update task state when scope or outcome changes materially.
- Close the task and session when the slice outcome is known.

## Evidence / Done
- active task and session ids are explicit
- worktree binding is correct
- durable context was recorded when needed
- closeout state matches the actual outcome

## References
- `AGENTS.md`
- `docs/codememory-workflow.md`
- `docs/codememory-conventions.md`
