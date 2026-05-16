---
id: improvements-review-2026-05-16
title: my_opencode e2e review and improvement ledger
owner: agent
created_at: 2026-05-16T18:05:00-03:00
version: 1
risk_level: low
depends_on:
  - docs/plan/opencode-reliability-review-runbook.md
  - instructions/plan_artifact_contract.md
  - instructions/pr_review_rubric.md
---

# Plan

- [x] 1. Review current branch context, runbook guidance, and validation expectations before new edits.
- [x] 2. Create a shared root review ledger that another AI can resume without chat history.
- [x] 3. Land the first low-risk improvement found during the review pass.
- [ ] 4. Continue the runbook-driven e2e review in small validated slices and record each finding/remediation here.
- [x] 5. Append end-of-session learnings, ideas, blockers, and the next concrete action.

## Scope

Review and improve `my_opencode` end to end from the docs/reliability/operator-guidance side, using the new reliability runbook as the execution anchor.

## Context reviewed

- `AGENTS.md`
- `docs/plan/opencode-reliability-review-runbook.md`
- `docs/quickstart.md`
- `docs/operator-playbook.md`
- `docs/parallel-wt-playbook.md`
- `instructions/pr_review_rubric.md`
- `instructions/plan_artifact_contract.md`
- sibling canonical reference: `../agents_md/docs/validation-policy.md`

## Validation plan for this slice

- `git diff --check`
- `make validate`

## Review ledger

### Session 1 — 2026-05-16

- branch: `feat/opencode-reliability-validation-review`
- objective: create the durable review ledger, continue the runbook iteration, and land the first concrete improvement.
- completed:
  - reviewed current worktree, remote status, recent commits, Codememory state, and relevant review docs
  - created Codememory task `task_5` and session `session_5` for this continuation slice
  - confirmed a real docs reliability gap: local `docs/validation-policy.md` was referenced by repo instructions but missing in this checkout
  - added a repo-local `docs/validation-policy.md` so future sessions have a local validation-policy reference during startup/review
- validation:
  - `git diff --check`
  - `make validate`
- blocker:
  - none for this slice
- next:
  - validate the docs slice
  - append a runbook ledger update for this new review iteration
  - continue with the next runbook-backed review finding

## Findings

### F-001 Missing repo-local validation-policy reference

- area: operator docs / session startup guidance
- trigger: `AGENTS.md` and related docs told the agent to consult `docs/validation-policy.md`, but the file did not exist in this repo worktree.
- expected: local startup/review instructions should resolve to a real repo file when they name a local path.
- actual: the reference existed only in external/sibling docs, which breaks local lookup and slows review startup.
- impact: unnecessary context friction during review iterations; easy to miss the intended risk matrix and review budget.
- evd:
  - `AGENTS.md`
  - `README.md:28`
  - `docs/quickstart.md:140`
  - `docs/operator-playbook.md:36`
  - missing file check on 2026-05-16: `test -f docs/validation-policy.md` -> false
- likely cause: local references were updated before a repo-local copy/shim was added.
- fix idea: keep a repo-local reference copy/shim aligned with the upstream `agents.md` validation policy.
- status: fixed

## Improvements landed

1. Added `docs/validation-policy.md` as a local validation-policy reference with repo-appropriate gate/risk guidance and an upstream-source note.

## Next-slice backlog

- continue R0-R2 execution from the runbook with real command evidence
- review whether other local-path docs named in `AGENTS.md` are also missing or stale
- decide whether this branch has reached a commit-worthy docs milestone after validation

## Ideas and learnings

- keep this file append-only; future sessions should add a new `Session <n>` block instead of rewriting prior evidence
- when a repo instruction names a local file path, verify the file exists before assuming the policy surface is complete
- the runbook is a strong campaign-level tracker; this root file is better for day-by-day iteration state and resumable review notes
