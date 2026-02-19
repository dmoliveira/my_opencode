# E8 Plan-Handoff Continuity Mapping

Owner: `br` task `bd-2md`
Date: 2026-02-19

## Goal

Map `@plan`-style continuity behavior onto existing local runtime surfaces without introducing a second planner/runtime engine.

Canonical surfaces to reuse:

- `/plan-handoff` as thin compatibility profile for continuity phase guidance (`status`, `plan`, `execute`, `resume`, `handoff`, `stop`)
- `/autopilot` for bounded execution lifecycle (`go`, `status`, `resume`, `stop`, `report`)
- `/task` for persistent dependency-aware task graph state
- `/resume` and checkpoint/runtime state for deterministic continuation after interruption
- `/start-work` for strict plan artifact execution when explicit plan files are used

## Continuity Mapping (E8-T1)

| `@plan`-style intent | Canonical local flow | Notes |
| --- | --- | --- |
| Generate/confirm execution plan before acting | `/plan-handoff plan` plus `/task ready --json` | Use compatibility profile guidance before starting bounded execution. |
| Start execution with tracked progress | `/autopilot-go "<goal>"` | Runtime state and blockers remain authoritative in `/autopilot-status`. |
| Keep continuity when context/session changes | `/plan-handoff resume` then `/resume status --json` | Resume path is deterministic and must preserve stop/budget/todo guardrails. |
| Preserve pending work between loops | `/task ready --json` and checkpoint-backed runtime status | Task graph is the durable pending-work source; checkpoints augment run context. |
| Handoff across runs/agents | `/plan-handoff handoff` + `/autopilot-report` + `/digest run --reason manual` | Report captures deviations/recovery trail; digest captures concise handoff summary. |
| End run safely | `/plan-handoff stop` + `/autopilot-stop --reason "manual_handoff"` | Stop is explicit, auditable, and prevents hidden loop continuation. |

## Acceptance Checks

1. Compatibility remains thin mapping over existing `/autopilot`, `/task`, `/resume`, and `/checkpoint` runtime surfaces.
2. No second runtime store is introduced; existing task graph + checkpoint/autopilot runtime remain sources of truth.
3. Resume behavior remains deterministic and guardrail-aware (`todo`, budget, stop guards).
4. Handoff evidence is available through existing report/digest/status commands.

## Follow-up for E8-T2+

- Add a thin compatibility profile/entrypoint that points users to the canonical flow above.
- Add selftests covering handoff transitions (normal, blocked, and recovery).
- Add README examples for continuity handoff using `/autopilot` + `/task`.

## Migration Examples (Canonical Commands)

Example 1: plan and begin execution

```bash
/plan-handoff plan
/autopilot-go "implement <objective>"
```

Example 2: interruption and deterministic resume

```bash
/plan-handoff resume
/resume-now
/autopilot-resume
```

Example 3: handoff to next cycle/agent

```bash
/plan-handoff handoff
/autopilot-report
/task ready --json
```
