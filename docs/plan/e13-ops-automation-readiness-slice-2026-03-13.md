# E13 Ops Automation Readiness Slice - 2026-03-13

Status: `doing`
Branch: `feat/ops-automation-slice-1`
Worktree: `/Users/cauhirsch/Codes/Projects/my_opencode-wt-ops-automation-slice-1`

## Why this slice first

E13 still lists operations automation expansion as a P0 gap. The current runtime already has canonical commands for the main operator lanes:

- issue delivery: `/delivery`
- release PR prep: `/ship`
- release packaging/publish: `/release-train`
- incident response: `/hotfix`

The immediate gap is not missing commands. It is missing cross-surface readiness visibility before operators depend on those commands more heavily.

## Open requirements extracted from current docs

- improve issue, PR, release, and hotfix automation without creating a second overlapping command family
- keep canonical commands as the source of truth
- land docs, diagnostics, and validation in the same slice when workflow behavior changes
- make the first slice small enough to ship quickly, then deepen toward higher-touch automation later

Primary source references:

- `docs/plan/e13-shared-memory-swarm-plugin-ops-plan.md`
- `docs/plan/current-roadmap-tracker.md`
- `docs/plan/release-milestone-automation-runbook.md`

## First-slice scope

1. add `/ship doctor` so PR/release readiness can be audited directly from the canonical ship surface
2. wire `/ship doctor` into umbrella `/doctor`
3. refresh operator docs so the canonical issue/PR/release/hotfix path is easier to discover
4. add selftest coverage for the new readiness path

## Explicit non-goals

- no new top-level ops command
- no issue creation wrapper yet
- no automatic PR/release execution beyond current guarded flows
- no hotfix workflow redesign in this slice

## Next slice candidates after this lands

1. add higher-touch delivery-to-ship handoff summaries from canonical runtime state
2. add release PR scaffolding that consumes delivery/workflow evidence directly
3. add deterministic hotfix-to-followup issue linkage audits in umbrella doctor output
