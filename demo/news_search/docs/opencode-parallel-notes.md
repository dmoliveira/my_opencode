# OpenCode Parallelization Notes

## What was executed in parallel

1. Discovery and architecture planning were delegated to subagents (`explore`, `strategic-planner`).
2. Validation commands were run in parallel where independent:
   - ingestion + unit tests
   - Python compile check + local review check

## What did not parallelize fully

- Final code writing remained single-writer to avoid merge overlap.
- A `reviewer` subagent pass failed to inspect this worktree path because it resolved to the primary workspace root.

## Fast parallel flow to use next

1. Reserve disjoint paths up front (backend, frontend, ingestor, docs).
2. Keep max two active parallel tracks at once.
3. Use subagents for read-only discovery/planning/review.
4. Run validations in parallel per independent command groups.
5. Merge into one integration worktree branch, then run a final single review gate.
