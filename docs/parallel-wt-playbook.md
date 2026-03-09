# Parallel WT Playbook

Use this as the default task-start checklist. Parallel delegation adds reservations on top of the same worktree-first rule.

## 1) Prepare branch and reservations

1. Create a dedicated worktree branch for the task from the current root branch.
2. Leave the main project folder on `main`; do not edit task files there.
3. Never `git checkout` or `git switch` the main project folder onto a task branch.
4. Treat linked worktrees as the normal editing surface; only block them when that linked worktree itself is on a protected branch.
5. For parallel work, split planned edits into disjoint path reservations.
6. Set reservation state:

```text
/reservation set --own-paths "plugin/gateway-core/src/**" --active-paths "plugin/gateway-core/src/**,docs/**" --writer-count 2
```

7. Confirm:

```text
/reservation status --json
```

## 2) Delegate safely

1. Keep at most two concurrent subagents.
2. Use `explore` + `strategic-planner` for fan-out discovery/planning.
3. Keep a single writer per reserved path.
4. If a delegation is blocked, capture the blocker text and retry with adjusted sequencing.

## 3) Validate by lane and globally

1. Lane checks after each meaningful slice (targeted lint/tests).
2. Shared integration gate before PR:
   - `npm --prefix plugin/gateway-core run lint`
   - `npm --prefix plugin/gateway-core run test`
   - `make validate`
   - `pre-commit run --all-files`

## 4) Merge and cleanup

1. Open PR with summary + validation evidence.
2. Merge with delete branch.
3. Sync the main worktree only from a checkout that is already on `main`.
4. Clear reservation state:

```text
/reservation clear
```

## Pilot evidence (Wave 2)

- Reservation state set successfully via `scripts/reservation_command.py` and verified with `--json`.
- Gateway hook simulations now confirm same-session fan-out is allowed when delegations are differentiated:
  - mixed subagents in one session without explicit traces are allowed by `subagent-lifecycle-supervisor`
  - `delegation-concurrency-guard` counts mixed subagents separately instead of collapsing them into one session slot
- Live tool-layer fan-out can still block a second concurrent subagent launch with:
  - `Blocked delegation: subagent session ... is already running for explore.`

This means reservation-first parallel worktree flow is operational, gateway runtime guards now better distinguish different delegations, and the remaining live blocker still needs deeper tracing at the task-runner boundary before we can claim a single root cause.
