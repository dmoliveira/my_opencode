# Autoflow Command Contract

Epic 22 Task 22.1 defines the baseline contract for `/autoflow` orchestration.

## Goals

- provide one deterministic orchestration surface over plan, todo, budget, and recovery primitives
- keep default usage safe and auditable with explicit validation and recovery conditions
- preserve machine-readable output for automation while keeping concise human summaries

## Command surface

`/autoflow` supports these subcommands:

- `start <plan.md>`: run orchestration with guardrails
- `status`: show latest orchestration state
- `resume`: attempt deterministic recovery from latest checkpoint/resume context
- `report`: emit run summary with deviations, budget, and recovery trail
- `doctor`: inspect current command/backend readiness and configuration state

## Input and validation contract

`start` accepts plan artifacts matching `instructions/plan_artifact_contract.md`.

Validation requirements:

- fail before execution when plan metadata/checklist validation fails
- fail when todo compliance preconditions are violated
- fail when runtime state is already non-recoverable and requires operator intervention
- fail when configured budget policy is invalid or contains non-positive overrides

Deterministic validation error shape:

- top-level `result: FAIL`
- stable `code` (for example: `validation_failed`, `todo_non_compliant`, `budget_config_invalid`, `resume_not_eligible`)
- `violations[]` entries with `code`, `message`, and optional `path`/`line`
- `remediation[]` with actionable next commands

## Output modes

### Concise mode (default)

Current human-readable output is subcommand-specific:

- `start`: plan path, final `status`, step progress, deviation count, and selected compliance/budget summaries
- `status`: current `status`, step progress, completion-gate summary when present, and config path
- `report`: deviations-oriented summary delegated from the backend `deviations` view
- `resume`: backend recovery summary for the selected interruption class
- `doctor`: backend doctor summary plus active routing entrypoint metadata

### Verbose mode (`--json`)

Machine-readable payloads differ slightly by subcommand, but the currently emitted top-level fields are:

- `start --json` (foreground execution): `result`, `status`, `plan`, `step_counts`, `deviation_count`, `todo_compliance`, `budget`, `checkpoint`, `config`, `model_routing`, plus shared task-graph fields
- `start --background --json` (queued execution): `result`, `status`, `background`, `job_id`, `evidence`, `plan`, `hint`, `model_routing`
- `status --json`: `result`, `status`, `plan`, `step_counts`, `todo_compliance`, `completion_gates`, `completion_gate_status`, `budget`, `config`, `model_routing`, plus shared task-graph fields
- `report --json`: `result`, `state`, `status`, `phase`, `plan`, `summary`, `step_counts`, `todo_compliance`, `budget`, `blockers`, `next_actions`, `recommendations`, `deviations`, `task_graph_path`, `task_graph`, `config`, `quick_fixes`, `model_routing` (treat `status/state/phase` as the authoritative run outcome fields; `result` is wrapper-level command success today)
- `resume --json`: backend `recover` payload with `model_routing.entrypoint = "autoflow"`
- `doctor --json`: backend `doctor` payload with `model_routing.entrypoint = "autoflow"`

Shared runtime authority:

- `task_graph.json` is the authoritative dependency graph store for canonical local flows.
- `/autoflow` runtime/checkpoint files remain command-local execution metadata and must not create a second dependency graph schema.
- `/autoflow status --json` and `/autoflow report --json` should expose `task_graph_path` so operators can inspect the shared graph with `/task` commands.
- `/autoflow status --json` and `/autoflow report --json` should also set `model_routing.entrypoint = "autoflow"` so command identity does not leak the `/start-work` backend.

## Lifecycle states

Current emitted status values across active `/autoflow` flows:

- `queued`
- `idle`
- `in_progress`
- `completed`
- `failed`
- `budget_stopped`
- `resume_escalated`

Background start is the main queued path. Status/report payloads otherwise mirror the underlying plan-execution runtime states.

## Safety defaults

- `start` enforces todo compliance and budget checks before any destructive step
- `resume` is gated by interruption class and idempotency checks

## Integration expectations for Task 22.2+

- compose existing engines from `/start-work`, `/todo`, `/resume`, `/checkpoint`, and budget runtime
- keep reason-code vocabulary stable across subcommands
- ensure `/doctor run --json` can consume `/autoflow` health state without extra parsing rules
