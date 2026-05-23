---
name: validation-fast-path
description: Use when choosing the smallest sufficient validation bundle for docs, config, skills, Python scripts, or other low-blast-radius changes.
---

## Goal
Select the smallest validation bundle that still proves the current slice is done.

## Use When
- the task is docs-only or low-risk
- the main question is which checks are enough
- validation should stay fast and deterministic
- the change touches config, skills, or Python scripts

## Do Not Use When
- the task is high-risk, security-sensitive, or migration-heavy
- a live-state or browser validation path is clearly required
- full repo CI is already the explicit ask

## First Steps
- Name the validation bundle before editing.
- Start with `git diff --check` for docs, config, or skills changes.
- Add `python3 -m py_compile <touched-files>` when Python scripts change.
- Broaden to targeted lint, test, or selftest only when the touched surface requires it.

## Working Rules
- Match validation depth to risk, not habit.
- Run quick smoke checks during iteration only when they reduce risk.
- Run the required gate once on the current full diff before claiming done.
- Re-run validation only if the diff changes after review or CI fails.
- Prefer one strong realistic smoke path over many weak speculative checks.

## Evidence / Done
- The chosen validation bundle is explicit.
- Required checks ran on the current diff.
- Failures were fixed or a concrete blocker was recorded.
- No broader suite was skipped without a reason.

## References
- `AGENTS.md`
- `docs/validation-policy.md`
- `docs/iterative-testing-workflow.md`
- `docs/tooling-quick-ref.md`
