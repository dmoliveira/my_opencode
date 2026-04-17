# OX command pack

The `ox` namespace is the custom prompt-pack layer for reusable OpenCode automation.

Use it when you want a stable short prefix, a predictable expansion format, and room to keep growing your own command family without colliding with the built-in surfaces.

## Why `ox`

- short enough to type constantly
- distinct from built-in commands
- works as both a namespace root (`/ox`) and a family prefix (`/ox-*`)
- designed for prompt expansion first, automation second

## Command family

```text
/ox
/ox doctor
/ox ecosystem
/ox-ux
/ox-review
/ox-ship
/ox-start
/ox-wrap
/ox-debug
/ox-refactor
```

## Design contract

Each `/ox-*` command expands into a stable execution contract with:

- objective
- scope
- recommended agent/tooling
- execution checklist
- acceptance checklist
- linked ecosystem references

The command output is intentionally prompt-friendly so you can paste or invoke it directly inside OpenCode and keep iterating without rewriting the same request.

## Command reference

### `/ox`

Namespace catalog and diagnostics.

Examples:

```text
/ox
/ox doctor
/ox ecosystem
/ox doctor --json
```

### `/ox-ux`

Browser-first UX audit and polish workflow.

Best for:

- site-wide Playwright reviews
- design polish passes
- onboarding/pricing/dashboard friction cleanup
- responsive and interaction-quality passes

Examples:

```text
/ox-ux
/ox-ux --repo top-uni
/ox-ux --target https://dmoliveira.github.io/top-uni/ --scope "home, filters, spotlight pages"
/ox-ux --target https://dmoliveira.github.io/top-uni/ --focus hierarchy,copy,states --goal "polish the browsing flow"
```

### `/ox-review`

End-to-end code review and improvement workflow.

Best for:

- "review this feature and improve it"
- pre-PR hardening
- feature cleanup after implementation

Examples:

```text
/ox-review
/ox-review --scope scripts --goal "review command ergonomics and simplify the rough edges"
/ox-review "review this code end to end and make it cleaner"
```

### `/ox-ship`

Ship-readiness pass for current branch validation and PR prep.

Examples:

```text
/ox-ship
/ox-ship --base main --head HEAD --goal "prepare this branch for PR"
```

### `/ox-start`

Task bootstrap flow with worktree/scope/validation cues.

Examples:

```text
/ox-start --scope "new command family for reusable prompts"
/ox-start --issue issue-900 --goal "bootstrap this task cleanly"
```

### `/ox-wrap`

Session wrap-up and handoff flow.

Examples:

```text
/ox-wrap
/ox-wrap --goal "close this session with digest and next actions"
```

### `/ox-debug`

Debug-and-fix workflow with reproduction and regression focus.

Examples:

```text
/ox-debug --target "failing mobile nav state"
/ox-debug "reproduce the issue, fix root cause, and add regression coverage"
```

### `/ox-refactor`

Safe refactor workflow with bounded scope and validation cues.

Examples:

```text
/ox-refactor --scope scripts/ox_command.py
/ox-refactor --scope src/components --goal "simplify this without behavior drift"
```

## Suggested operator pattern

Use the `ox` family like this:

1. choose the nearest `/ox-*` intent
2. add `--scope`, `--goal`, `--target`, or freeform trailing context
3. let the expansion become the execution contract for the turn
4. only reach for a brand-new custom prompt when none of the existing `ox` shapes fit

## Auto-slash shortcuts

The `auto-slash` detector now recognizes common `ox` intent shapes, especially when you use short prompt prefixes.

Examples:

```text
/auto-slash preview --prompt "(playwright) analyze the website and polish the UX" --json
/auto-slash preview --prompt "review this code and improve end to end" --json
/auto-slash preview --prompt "is this branch ready to ship?" --json
```

Expected mappings:

- `(playwright)` or strong UI/UX polish prompts -> `/ox-ux`
- review/improve end-to-end prompts -> `/ox-review`
- ship-readiness / PR-prep prompts -> `/ox-ship`

This keeps the shorthand deterministic while preserving the stable `/ox-*` command family as the canonical surface.

## Continue-the-cycle commands

Yes — this repo already has commands for continuing an execution loop.

Use:

```text
/autopilot go --goal "continue active objective" --max-cycles 10 --json
/autopilot resume --json
/resume now --interruption-class tool_failure --json
/resume smart --json
/continuation-stop --reason "manual checkpoint" --json
```

Practical split:

- `/autopilot go` -> start or keep iterating through the next bounded cycles
- `/autopilot resume` / `/resume now` -> continue after interruption
- `/resume smart` -> triage and continue with recovery hints
- `/continuation-stop` -> intentionally stop the loop

## Ecosystem links

Current linked references in this command pack:

- `my_opencode` — https://github.com/dmoliveira/my_opencode
- `agents.md` — https://github.com/dmoliveira/agents.md
- `top-uni` — https://dmoliveira.github.io/top-uni/
- `my-cv-public` — https://dmoliveira.github.io/my-cv-public/cv/human/

The Top Uni site is the default public example target for `/ox-ux` because it is ideal for browser-first audit and polish testing in isolation.
