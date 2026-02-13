# Team Rule Pack Examples

This guide provides concrete rule-pack examples for Epic 9 Task 9.4.

## Suggested repository layout

```text
.opencode/
  rules/
    python/
      strict-style.md
    docs/
      changelog-quality.md
    global/
      safety.md
```

## Example: Python strict style rule

```markdown
---
id: python-strict-style
description: Enforce explicit typing and safe refactor defaults for Python edits
priority: 80
globs:
  - "scripts/**/*.py"
---
Prefer explicit type hints for new functions and avoid broad refactors without validation evidence.
```

## Example: Changelog quality rule

```markdown
---
id: changelog-quality
description: Keep changelog entries concise and user-facing
priority: 60
globs:
  - "CHANGELOG.md"
---
Summarize impact in user-facing language and avoid internal-only implementation details.
```

## Example: Global safety rule

```markdown
---
id: global-safety
description: Baseline safety constraints
priority: 40
alwaysApply: true
---
Do not run destructive operations without explicit user intent and include verification after non-trivial edits.
```

## Conflict and precedence notes

- Higher `priority` wins.
- For equal priority, project rules override user rules.
- For equal priority and same scope, lexical rule id order is deterministic.
- Duplicate rule ids are reported as conflicts; first winner remains active.
