# Orchestration Advanced

Use this guide when work is multi-file, dependency-heavy, under process pressure, or needs stricter sequencing than the default small-slice loop.

Primary operating contract stays in `AGENTS.md`. Use this page only when advanced controls help.

## Parallel execution

- Use one worktree branch per focused delivery slice.
- Keep one writer per overlapping path.
- Keep at most two concurrent subagents.
- Prefer read-only fan-out first, then a single integrating writer.

## Worker packet checklist

Include:

1. objective
2. scoped ownership
3. constrained file paths
4. acceptance criteria
5. required validation
6. expected evidence format

## Review/fix budget

- low risk: 1 review/fix pass
- medium risk: 2 review/fix passes
- high risk: 3-5 review/fix passes

Do not repeat reviewer/verifier passes on unchanged diffs.

## Sequencing guidance

- Capture the smallest useful plan before coding when work is `medium` or `large`.
- Keep dependency graphs compact: objective, slices, dependency edges, required checks, current next slice.
- Prefer finishing the active worktree card before opening another long-lived slice.

## Pressure-mode defaults

- low pressure: normal flow; limited delegation is fine
- medium pressure: one active subagent total; skip non-essential review passes unless checks fail
- high pressure: no new subagents unless a blocker or high-severity risk requires them

## Validation reminders

- Follow `docs/validation-policy.md` for the base gate policy.
- Prefer one stronger realistic E2E/sandbox check over many weak speculative checks when behavior matters.
- Re-check remote branch/PR state before merge if the branch stays open across longer sessions.
