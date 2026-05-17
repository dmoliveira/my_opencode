# Iterative Testing Workflow

Use this optional module when confidence depends on current runtime state, session state, or a realistic isolated environment rather than static inspection alone.

## Mode model

- `off`: do not apply by default
- `auto`: apply when the task is stateful or iterative and the needed runtime/tooling is available
- `on`: treat it as standard validation guidance for applicable tasks

Mode precedence:

1. explicit user request
2. repo/runtime mode in `AGENTS.md`
3. default behavior

## When to use it

Use it when one or more are true:

- the bug or feature depends on current CLI/TUI/app state
- the fastest trustworthy signal comes from observing a running process
- static checks are necessary but not sufficient
- one stronger sandbox pass would materially increase confidence

## Live-state validation

- Prefer live-state validation when failures surface in the running process.
- Start with a short smoke path.
- Broaden only if confidence is still low.

Examples:

- multi-step CLI flows
- long-running daemons or watchers
- tmux-backed or backgrounded task flows
- stateful local apps

## `tmux` guidance

If terminal/session state is the blocker and `tmux` is available:

- inspect the live pane instead of restarting blindly
- use stable names such as `ai-oc-<task>`
- send non-interactive commands into the running session when needed

## Sandbox guidance

Use the strongest realistic isolated environment available without turning a normal task into a heavyweight lab exercise.

Examples:

- disposable temp workspace
- dedicated worktree
- isolated config/profile directory
- ephemeral test database or service container

## Boundaries

- Do not replace core lint/test/build gates with this workflow.
- Do not use browser automation when shell-side live-state inspection is enough.
- If the blocker is browser-owned state, switch to `docs/agent-browser.md`.
- Keep commands reproducible and non-interactive.

## Evidence to record

When used for meaningful work, record:

- runtime or sandbox path used
- key command(s) run
- observed result that increased confidence
