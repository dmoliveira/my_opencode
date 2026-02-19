# E9 Release-Note Automation Baseline

Owner: `br` task `bd-2vf`
Date: 2026-02-19

## Goal

Reduce manual changelog drift by adding a lightweight release-note automation baseline for parity and LSP milestone waves.

## Scope (Cycle 2)

- In scope:
  - re-scan post-E8 parity backlog and confirm highest-value next slice
  - baseline release-note generation from merged PR metadata and milestone plan docs
  - docs + validation updates for repeatable release-note workflow
- Out of scope:
  - MCP OAuth/provider expansion (`E7`)
  - broad release system rewrites

## Checklist

- [x] E9-T1 Re-scan backlog evidence
  - [x] confirm remaining high-value gaps from current docs and command surface
  - [x] lock next implementation slice with acceptance criteria
- [x] E9-T2 Implement automation baseline
  - [x] add script/command pathway for consolidated release-note draft generation
  - [x] include parity + LSP milestone wave inputs
- [x] E9-T3 Validate and document
  - [x] run validation/selftest evidence for added workflow
  - [x] update README/docs with usage example and failure guidance

## Acceptance Criteria

1. A repeatable command or script produces a draft release-note summary from local project evidence.
2. Workflow is documented with at least one practical example.
3. Validation evidence is captured in the delivery slice.

## Validation Evidence

- `python3 scripts/release_train_command.py draft --include-milestones --head HEAD --json`
- `python3 scripts/release_train_engine.py draft --include-milestones --head HEAD --json`
- `make validate`
- `make selftest`
