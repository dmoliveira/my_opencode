# /refactor-lite Command Contract (E3-T1)

This contract defines the behavior of `/refactor-lite` before backend implementation.

## Syntax

Primary form:

```text
/refactor-lite <target> [--scope <path|glob>] [--strategy safe|balanced|aggressive] [--dry-run] [--json]
```

Shortcuts:

- `/refactor-lite <target>` defaults to `--strategy safe` and inferred scope from current repo.
- `--scope` accepts comma-separated file paths or globs (`src/**/*.py,tests/**`).
- `--dry-run` prints plan and validation steps without writing changes.

## Safe defaults and guardrails

- Default strategy is `safe`.
- `safe` mode must:
  - require explicit target text (no empty target)
  - produce a deterministic edit plan before mutation
  - run `make validate` before reporting success
- `balanced` mode may touch broader scope but still runs validation gates.
- `aggressive` mode is opt-in only and must print explicit risk note.
- If target resolution is ambiguous, command returns a structured failure with remediation hints.

## Output shape

Success (human):

- `result: PASS`
- `target: <target>`
- `scope: <resolved-scope>`
- `strategy: <safe|balanced|aggressive>`
- `changed_files: <count>`
- `validations: <list with pass/fail>`
- `next: <optional follow-up commands>`

Failure (human):

- `result: FAIL`
- `error_code: <category>`
- `reason: <concise explanation>`
- `remediation: <1-3 concrete commands/actions>`

JSON mode (`--json`):

```json
{
  "result": "PASS|FAIL",
  "target": "...",
  "scope": ["..."],
  "strategy": "safe|balanced|aggressive",
  "changed_files": 0,
  "validations": [
    {"name": "make validate", "ok": true, "exit_code": 0}
  ],
  "error_code": null,
  "reason": null,
  "remediation": [],
  "next": []
}
```

## Non-goals for Task 3.1

- No code edits/execution backend yet.
- No command registration in `opencode.json` yet.
- No AST/LSP integration yet (covered by later epics/tasks).
