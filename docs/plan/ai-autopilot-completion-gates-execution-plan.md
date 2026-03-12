# AI Autopilot Completion Gates Execution Plan

Date: 2026-03-12
Status: `proposed`
Parent plan: `docs/plan/ai-native-autopilot-orchestration-plan.md`
Scope: first execution slice for E3 completion-gate unification plus a thin E1 ownership foundation

## Goal

Turn completion from a reminder-style pattern into a shared runtime contract that `/autopilot`, gateway evidence hooks, and shared task/todo metadata can evaluate consistently in this first slice, while keeping `/autoflow` convergence explicitly in scope for follow-up adoption.

This slice does not yet implement same-worktree write leases. It focuses on trust and finish-state correctness first.

## Current grounding

- `/autopilot` already validates objective shape and stores normalized `done_criteria` in runtime state via `scripts/autopilot_runtime.py:53` and `scripts/autopilot_runtime.py:84`
- `/autopilot` already exposes lifecycle commands and report/doctor surfaces via `scripts/autopilot_command.py:31`
- todo compliance already blocks completion when pending work remains via `scripts/todo_enforcement.py:16` and `scripts/todo_enforcement.py:99`
- task graph runtime already persists task ownership and dependency structure in a machine-readable store via `scripts/task_graph_runtime.py:17` and `scripts/task_graph_runtime.py:75`
- `done-proof-enforcer` already checks completion text against required evidence markers via `plugin/gateway-core/src/hooks/done-proof-enforcer/index.ts:26`
- `validation-evidence-ledger` already records validation categories from command execution via `plugin/gateway-core/src/hooks/validation-evidence-ledger/index.ts:14` and `plugin/gateway-core/src/hooks/validation-evidence-ledger/index.ts:137`

## Problem to solve in this slice

Completion evidence is currently split across several layers:

- objective done criteria in the Python runtime
- todo completion rules in the compliance model
- task graph ownership/dependency metadata in a separate runtime store
- hook-level proof enforcement and validation evidence in gateway-core

The repo needs one canonical completion-gate schema so these layers can agree on:

- what must be true before a task or objective can become `done`
- what evidence satisfies each requirement
- which command/runtime surface reports missing proof
- how remediation is explained back to the agent

## Deliverables

### D1. Shared completion-gate schema

Add one small schema that can describe required finish conditions for both task-level and objective-level completion.

Proposed fields:

- `required_validation`: `lint|test|typecheck|build|custom`
- `required_markers`: proof markers already understood by `done-proof-enforcer`
- `required_task_ids`: task dependencies that must be closed
- `required_owner`: optional owner or delegated role for accountable completion
- `allow_bypass`: explicit policy-controlled bypass settings
- `evidence_mode`: `ledger_only|text_fallback|hybrid`

Primary file targets:

- new shared Python module near `scripts/autopilot_runtime.py`
- new shared TypeScript helper near `plugin/gateway-core/src/hooks/shared/`
- docs references in `docs/plan/ai-native-autopilot-orchestration-plan.md`

### D2. Objective runtime adoption

Teach the autopilot runtime to normalize and persist completion gates, not just free-form done criteria.

File targets:

- `scripts/autopilot_runtime.py`
  - add gate normalization/parsing alongside `_normalize_done_criteria`
  - persist structured gate state in runtime payloads
  - expose missing-gate diagnostics in cycle/report output
- `scripts/autopilot_command.py`
  - surface gate failures consistently in `status`, `report`, and `doctor`
  - keep `/autopilot` as the open-ended execution mode; do not add a duplicate command surface

Acceptance:

- objective-mode runs can report which gate is unmet
- runtime state includes normalized gate metadata instead of only plain done-criteria strings

### D2b. `/autoflow` follow-up adoption seam

Keep this slice honest about the current command hierarchy: `/autoflow` is a real public surface, but this first implementation pass is `/autopilot`-first.

File targets:

- `scripts/autoflow_command.py`
  - audit whether plan execution state can consume the shared completion-gate schema without a second gate model
  - document any adapter work needed for a follow-up convergence slice
- `scripts/doctor_command.py`
  - keep `/autoflow` health reporting compatible if gate metadata starts appearing in shared runtime state

Acceptance:

- this slice does not claim `/autoflow` completion-gate parity unless explicit command/backend updates land
- the follow-up work needed for `/autoflow` adoption is documented rather than implied

### D3. Plan/todo ownership foundation

Use the existing task graph and todo runtime as the thin E1 bridge for accountable completion.

File targets:

- `scripts/task_graph_runtime.py`
  - extend normalized task metadata to carry completion-gate hints and required artifacts
  - keep `owner` and dependency fields canonical for future self-claim logic
- `scripts/todo_enforcement.py`
  - allow completion checks to reference task-level gate state rather than only raw todo state
- `scripts/task_graph_command.py`
  - expose gate-related integrity failures through command diagnostics if needed

Acceptance:

- a task can declare required finish evidence in machine-readable metadata
- pending dependencies or missing required artifacts block task completion deterministically

### D4. Gateway hook convergence

Unify hook-level evidence logic around the shared gate vocabulary.

File targets:

- `plugin/gateway-core/src/hooks/done-proof-enforcer/index.ts`
  - consume canonical required markers and evidence mode
  - stop hard-coding assumptions that belong in shared gate config
- `plugin/gateway-core/src/hooks/validation-evidence-ledger/index.ts`
  - expose ledger evidence in a format that the gate evaluator can consume directly
- `plugin/gateway-core/src/hooks/mistake-ledger/index.ts`
  - record completion attempts that fail gates as structured mistake reasons instead of only narrative mismatch clues
- `plugin/gateway-core/src/hooks/post-merge-sync-guard/index.ts` and other deterministic policy guards stay unchanged unless they need to emit gate-compatible evidence only

Acceptance:

- gateway hooks share the same gate names and missing-proof reason vocabulary
- completion failure audits identify which gate failed, not just that completion was rejected

### D5. Operator/reporting surfaces

Make the gate state visible in the canonical command hierarchy.

File targets:

- `scripts/doctor_command.py`
  - include completion-gate health when objective/runtime state exists
- `scripts/post_session_command.py`
  - report missing gates as post-session blockers instead of generic incomplete status
- `scripts/delivery_command.py`
  - primary operator-facing surface if gate summaries need to appear in the default day-to-day flow
- `scripts/autoflow_command.py`
  - follow-up adoption target for the canonical plan-execution surface; audit/documentation only in this first slice unless explicit backend updates land
- `scripts/workflow_command.py`
  - only if lower-level workflow diagnostics need matching backend detail

Acceptance:

- `doctor` output can show which completion-gate requirements are unsatisfied
- post-session summaries point to exact missing artifacts
- `/autoflow` is either explicitly wired in a follow-up patch or explicitly left at audit/documentation-only scope for this slice

### D6. Selftest and scenario coverage

Add targeted scenarios before implementation is considered complete.

Primary file targets:

- `scripts/selftest.py`
- workflow scenario docs under `docs/plan/status/in_progress/`

Required scenarios:

- `CG1`: objective-mode autopilot run fails completion when normalized validation gates are missing
- `CG2`: a ledger-marked validation command satisfies the matching completion gate
- `CG3`: todo/task completion stays blocked when dependencies remain open
- `CG4`: done-proof marker text alone is insufficient when gate mode is `ledger_only`
- `CG5`: doctor/report surfaces show the same missing-gate reason code across Python and gateway layers

## Proposed implementation order

1. define the shared gate schema and reason codes
2. wire normalization into `scripts/autopilot_runtime.py`
3. wire task/todo metadata support into `scripts/task_graph_runtime.py` and `scripts/todo_enforcement.py`
4. adapt `done-proof-enforcer` and `validation-evidence-ledger` to the shared gate vocabulary
5. expose gate status in `autopilot report`, `doctor`, and post-session surfaces
6. add selftest and scenario coverage

## Explicit non-goals for this slice

- no same-worktree write scheduler yet
- no autonomous self-claim execution yet beyond storing the necessary ownership/dependency metadata
- no new slash command surface
- no LLM-first completion decisions for hard safety gates that can stay deterministic
- no claim of full `/autoflow` completion-gate adoption in this first slice without explicit command/backend updates

## Validation gates

- `npm --prefix plugin/gateway-core run test`
- `make selftest`
- `make validate`
- targeted docs consistency check if command contract text changes

## Risks and controls

- Risk: Python runtime and gateway-core drift on gate names
  - Control: define shared reason-code table and schema docs first
- Risk: completion becomes too strict and blocks legitimate docs-only flows
  - Control: keep gate profiles command-family aware and start with objective-mode plus explicit task metadata
- Risk: old reminder hooks conflict with new hard gates
  - Control: make hard-gate evaluation authoritative and downgrade reminder-only hooks to explanatory role where necessary

## Exit criteria

- completion gates are stored in structured form for objective runs
- task/todo metadata can declare required finish evidence and dependencies
- gateway evidence hooks emit gate-compatible pass/fail data
- `doctor` and `autopilot report` agree on missing completion requirements
- selftests cover the five `CG*` scenarios above
