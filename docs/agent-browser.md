# Agent browser workflow

Use this path only when the blocker is owned by browser state rather than shell-visible repo state.

## Use when

- OAuth consent or login must complete in-browser
- admin install, re-auth, or scope-upgrade UI must be clicked through
- final visual verification depends on rendered browser state
- browser-only prompts block shell automation from completing safely

## Default path

1. Run `/browser ensure --json`.
2. If browser tooling is not ready, fix that first instead of guessing.
3. Prefer Playwright/browser MCP for deterministic checks.
4. Keep shell validation for code, config, and build gates.
5. Record the exact browser-owned blocker and the observed UI outcome.

## Do not use when

- shell-side logs, APIs, files, or process state already prove the result
- the task is pure docs/config/test work
- a static review is enough and no browser state must change

## Minimal evidence

Capture:

- browser readiness command used
- target path or flow checked
- blocker or confirmation observed in UI
- follow-up shell command or validation gate that became unblocked

## Related references

- `docs/iterative-testing-workflow.md`
- `.opencode/skills/playwright-web-ux/SKILL.md`
- `docs/command-handbook.md`
