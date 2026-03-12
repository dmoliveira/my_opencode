---
status: doing
priority: high
updated: 2026-03-09
---

# Agent Parallelism Parity Roadmap

Date: 2026-03-09
Runtime session: `ses_32f8badadffebFo9zuEGQjhGxF`
Scope: close the remaining high-value gaps between `my_opencode` and `oh-my-opencode` for multi-agent parallelism, agent coverage visibility, orchestration direction, and runtime execution depth while preserving `my_opencode`'s stronger safety and operator guardrails.

## Why This Track Exists

- `my_opencode` is already strong on worktree safety, reservations, operator workflows, validation gates, and command breadth.
- `oh-my-opencode` is still ahead on true runtime parallelism, dependency-aware task scheduling, and sharper orchestrator behavior for multi-agent execution.
- The goal is not to clone upstream. The goal is to surpass it by combining our stronger governance surface with a more capable parallel execution runtime.

## Decision Summary

- Keep `worktree-first`, `protected-main`, and reservation safety as non-negotiable local advantages.
- Prioritize runtime concurrency and dependency scheduling before adding more orchestration command surface.
- Expose the existing planning-agent tier more clearly once the runtime can actually benefit from it.
- Prefer improving canonical local flows (`/workflow`, `/delivery`, `/autoflow`, `/autopilot`, `/agent-pool`, `/bg`) over introducing upstream-branded compatibility layers.

## Status Legend

- `backlog`: planned but not started
- `doing`: active implementation
- `blocked`: waiting on a concrete blocker
- `done`: implemented and validated

## Validation Gates

- `make validate`
- `make selftest`
- targeted command selftests for `/autoflow`, `/workflow`, `/agent-pool`, `/bg`, `/reservation`
- live linked-worktree fan-out scenarios for mixed and same-type subagents

## Epic Dashboard

| Epic | Priority | Status | Goal | Primary surface |
| --- | --- | --- | --- | --- |
| E1 Runtime fan-out completion | P0 | done | remove remaining same-session subagent launch blockers | task runner, gateway, lifecycle hooks |
| E2 Dependency-aware execution graph | P0 | done | schedule independent work in parallel with explicit dependencies | `/workflow`, `/autoflow`, task state |
| E3 Agent pool and background runtime hardening | P1 | done | make runtime worker management concrete, observable, and trustworthy | `/agent-pool`, `/bg`, runtime state |
| E4 Orchestrator direction and model routing upgrades | P1 | done | make orchestration prompts and routing sharper for parallel execution | `agent/orchestrator.md`, routing policy |
| E5 Planning tier productization | P1 | done | elevate planner/ambiguity/critic roles into normal operator flows | README, docs, command guidance |
| E6 Parity scoreboard and drift checks | P2 | done | track parity progress and prevent docs/config drift | docs, doctor checks, parity trackers |

## Epics And Tasks

### E1 Runtime fan-out completion

Status: `done`

- [x] E1-T1 Trace the remaining runner-boundary blocker behind same-session second-subagent failures and document the exact failure path.
- [x] E1-T2 Introduce a stable child run identifier for every delegated subagent execution, separate from parent session id.
- [x] E1-T3 Require structured delegation lifecycle payloads for launch, running, completion, and cleanup paths.
- [x] E1-T4 Remove the remaining prompt/output parsing fallbacks where structured identity is available.
- [x] E1-T5 Add stress coverage for `2-5` concurrent subagents with varied completion ordering and mixed subagent types.
- [x] E1-T6 Re-run linked-worktree protected-main scenarios to confirm no regression in safety guard behavior.

Definition of done:

- same-session mixed fan-out succeeds reliably
- same-session same-type fan-out succeeds reliably
- follow-up delegation after a parallel wave does not false-block
- live results remain reservation-safe and linked-worktree-safe

### E2 Dependency-aware execution graph

Status: `done`

- [x] E2-T1 Define a durable task graph schema for canonical local flows with `blockedBy`, `blocks`, ownership, and execution state.
- [x] E2-T2 Decide whether the source of truth belongs under `/workflow`, `/autoflow`, or shared runtime storage, then document the contract.
- [x] E2-T3 Implement ready-task selection so independent tasks can run in parallel while blocked tasks wait deterministically.
- [x] E2-T4 Integrate reservation awareness so schedulable work also respects disjoint writer ownership.
- [x] E2-T5 Add JSON/status/report output showing graph state, blocked reasons, and runnable lanes.
- [x] E2-T6 Add recovery/resume coverage for interrupted runs and partial completion states.

Definition of done:

- explicit task graphs can be created, resumed, and inspected
- independent lanes run concurrently when safe
- blocked tasks explain exactly why they are waiting
- reservation policy still overrides unsafe concurrency

### E3 Agent pool and background runtime hardening

Status: `done`

- [x] E3-T1 Audit `/agent-pool` versus `/bg` responsibilities and choose a single clear runtime ownership model.
- [x] E3-T2 Either deepen `/agent-pool` into real worker lifecycle management or narrow it to a thin observability facade.
- [x] E3-T3 Add runtime health signals for spawn failures, stuck workers, queue depth, and stale sessions.
- [x] E3-T4 Add parent-child evidence links so background results can be tied back to the initiating run and task graph node.
- [x] E3-T5 Add `doctor` coverage and operator docs for restart, drain, cleanup, and failure triage.

Definition of done:

- runtime ownership is conceptually simple
- operator can tell what is running, blocked, failed, or stale
- background execution is observable enough to trust in day-to-day use

### 2026-03-10 - E3-T1 ownership decision and surface alignment

Current status: `done`

Findings:

- Adopted the first ownership decision explicitly in command surfaces: `/bg` is the execution backend and `/agent-pool` is a manual capacity registry plus lifecycle control surface, not the backend itself.
- Added ownership metadata to `agent-pool` and `bg` JSON outputs so operators and downstream automation can tell which command owns execution versus capacity bookkeeping.
- Updated handbook wording and selftest coverage so the ownership split is documented and machine-checked without overstating behavioral coupling.

Validation:

- `python3 -m py_compile scripts/*.py && make selftest && make validate`
- fresh `opencode run` smoke: `e3-ownership-smoke-2` -> `PASS`

Immediate next slice:

- implement E3-T2 by either tightening `/agent-pool` into a clearer manual-capacity registry contract or wiring selected health views to `/bg` runtime signals where coupling is actually intended
- then add E3-T3 health signals for stale workers, queue depth, and spawn failures

### 2026-03-10 - E3-T3 runtime health signal baseline

Current status: `done`

Findings:

- Added concrete backend health signals to `/bg status --json` and `/bg doctor --json`: `queue_depth`, `stale_running`, and `failed_jobs`.
- Added `backend_health` passthrough on `/agent-pool health --json` so the manual capacity registry exposes current backend pressure without pretending to own execution.
- Extended selftest to assert those signals on both command surfaces and on `/bg doctor --json` plus `/agent-pool doctor --json`.
- Added umbrella `/doctor` coverage for `gateway`, `quality`, `devtools`, and `nvim` so the one-shot health sweep covers the documented doctor-capable runtime surfaces.

Validation:

- `python3 -m py_compile scripts/*.py && make selftest && make validate`
- fresh `opencode run` smoke: `e3-health-smoke` -> `PASS`

Immediate next slice:

- implement E3-T5 operator runbook guidance for restart, drain, cleanup, and failure triage now that the health signals exist
- then decide whether E3-T2 should remain a manual-capacity contract or grow selected backend-coupled facade behaviors

### 2026-03-10 - E3-T5 doctor coverage and operator guidance

Current status: `done`

Findings:

- Expanded umbrella `/doctor` to include documented doctor-capable subsystems `gateway`, `quality`, `devtools`, and `nvim`, while safely skipping resume-disabled and nvim-not-installed cases instead of hard-failing the entire sweep.
- Switched umbrella `/doctor` to read-only checks for `model-routing` and `todo` so the one-shot health sweep does not mutate routing state or fail just because active work is still in progress.
- Added operator guidance in the quickstart and command handbook for `/bg doctor --json`, `/agent-pool doctor --json`, drain, cleanup, and failure triage flows.
- Extended selftest to assert the added doctor checks and background/operator guidance signals.

Primary evidence references:

- `scripts/doctor_command.py`
- `scripts/selftest.py`
- `docs/command-handbook.md`
- `docs/quickstart.md`

### 2026-03-10 - E3-T4 background evidence links

Current status: `done`

Findings:

- Background job records now persist `evidence` derived from queue labels, including `parent_command`, `parent_session_id`, `plan_path`, `task_graph_path`, and optional parent run identifiers.
- `/start-work --background --json` now returns that evidence immediately, and queued `/bg read --json` exposes the same linkage so operators can trace queued work back to its initiating command and shared graph.
- `/bg status --json` and `/bg doctor --json` now aggregate evidence-link summaries for parent sessions and task graph paths.

Primary evidence references:

- `scripts/background_task_manager.py`
- `scripts/start_work_command.py`
- `scripts/selftest.py`
- `/tmp/e3-evidence-smoke-2.stdout`

Validation:

- `python3 -m py_compile scripts/*.py && make selftest && make validate`
- fresh `opencode run` smoke: `e3-evidence-smoke-2` -> `PASS`

Immediate next slice:

- decide E3-T2 conclusively: keep `/agent-pool` as a manual-capacity registry or deepen selective backend-coupled facade behavior
- if staying thin, close E3 by documenting the contract and polishing doctor/operator surfaces rather than inventing duplicate worker lifecycle machinery

### 2026-03-10 - E3-T2 thin registry contract closure

Current status: `done`

Findings:

- Closed the ownership decision in favor of a thin `/agent-pool` manual-capacity registry rather than a duplicate backend runtime.
- Added explicit contract markers to `/agent-pool spawn --json` and `/agent-pool doctor --json` so automation can tell that `/bg` owns execution.
- Tightened command handbook, quickstart, README, and selftest wording so the operator model is consistent across code and docs.

Primary evidence references:

- `scripts/agent_pool_command.py`
- `scripts/selftest.py`
- `docs/command-handbook.md`
- `docs/quickstart.md`
- `README.md`

E3 completion note:

- E3 is now complete: ownership is explicit, backend health signals are surfaced, parent-child evidence links are persisted, and doctor/operator guidance covers the runtime split.

### 2026-03-10 - E4-T1 planner routing and fan-in guidance alignment

Current status: `done`

Findings:

- Updated the orchestrator source spec so planner-heavy work (`strategic-planner`, `ambiguity-analyst`) routes to `deep` instead of `balanced`, matching the model allocation policy.
- Tightened orchestrator guidance so read-only discovery/planning fans out first, then implementation fans back in to a single writer by default.
- Regenerated `agent/orchestrator.md` from `agent/specs/orchestrator.json` and validated the generated artifact stays aligned.

Primary evidence references:

- `agent/specs/orchestrator.json`
- `agent/orchestrator.md`
- `docs/model-allocation-policy.md`

Validation:

- `python3 scripts/build_agents.py --profile balanced`
- `python3 scripts/agent_doctor.py run --json`
- fresh `opencode run` smoke: `e4-routing-smoke` -> `PASS`

### 2026-03-10 - E4-T5 `/autoflow` and `/autopilot` mental-model convergence

Current status: `done`

Findings:

- Normalized `/autoflow status --json` and `/autoflow report --json` so they present the same orchestration identity shape as `/autopilot` instead of leaking the `/start-work` backend entrypoint.
- Added explicit `state`/`phase` normalization and a real `/autoflow report` summary payload with deviations nested for compatibility.
- Added selftest coverage to assert `/autoflow` now reports `model_routing.entrypoint = "autoflow"` plus the shared task-graph path.

Primary evidence references:

- `scripts/autoflow_command.py`
- `scripts/selftest.py`
- `instructions/autoflow_command_contract.md`

Validation:

- `python3 scripts/selftest.py`
- `python3 -m py_compile scripts/*.py && make validate`
- fresh `opencode run` smoke: `e4-autoflow-smoke` -> `PASS`

### 2026-03-10 - E4-T4 planner bundle and operator guidance

Current status: `done`

Findings:

- Added a canonical operator playbook note for read-only fan-out first, then single-writer fan-in.
- Surfaced planner-tier agents in the cheatsheet and agents playbook so `strategic-planner`, `ambiguity-analyst`, and `plan-critic` are discoverable without reading source files.
- Clarified in the command handbook that `/autopilot` and `/autoflow` are orchestration siblings over the same task-graph mental model.

Primary evidence references:

- `docs/operator-playbook.md`
- `docs/agents-playbook.md`
- `docs/agents-cheatsheet.md`
- `docs/command-handbook.md`

Validation:

- `python3 -m py_compile scripts/*.py && make validate`
- fresh `opencode run` smoke: `e4-guidance-smoke` -> `PASS`

### 2026-03-10 - E4-T2 and E4-T3 task-graph delegation and routing defaults

Current status: `done`

Findings:

- Added explicit task-graph-aware delegation guidance so operators can read the intended fan-out/fan-in model without relying on the orchestrator prompt alone.
- Extended model-routing selftest coverage so `strategic-planner` and `ambiguity-analyst` recommend `deep`, while `plan-critic` recommends `critical`, matching the allocation policy.

Primary evidence references:

- `docs/agent-architecture.md`
- `scripts/selftest.py`
- `docs/model-allocation-policy.md`

Validation:

- `python3 scripts/selftest.py`
- `python3 -m py_compile scripts/*.py && make validate`

### E4 Orchestrator direction and model routing upgrades

Status: `done`

- [x] E4-T1 Tighten `orchestrator` prompt guidance for intent routing, parallelism triggers, and when to stay single-writer.
- [x] E4-T2 Add explicit guidance for task-graph-aware delegation: discover in parallel, implement in controlled lanes, validate before merge.
- [x] E4-T3 Review model-routing defaults so parallel read-only loops, planning passes, and critical reviews use the right category consistently.
- [x] E4-T4 Add concrete playbook examples showing when to use `explore`, `strategic-planner`, `ambiguity-analyst`, and `plan-critic` together.
- [x] E4-T5 Add command-level guidance so `/autopilot` and `/autoflow` converge on the same orchestration mental model.

Definition of done:

- orchestrator behavior is sharper and less ambiguous
- planning roles are integrated into normal orchestration decisions
- runtime and docs tell the same story

### E5 Planning tier productization

Status: `done`

- [x] E5-T1 Update README agent inventory so the planning specialist tier is visible and not buried.
- [x] E5-T2 Update `docs/agents-playbook.md` and operator docs with recommended planner bundles for complex work.
- [x] E5-T3 Add examples pairing planning agents with reservations and linked-worktree execution.
- [x] E5-T4 Reconcile `default_agent` documentation with actual config and intended operator guidance.
- [x] E5-T5 Add `agent-doctor` or catalog checks that flag inventory/documentation mismatches.

Definition of done:

- agent coverage is documented accurately
- users can discover the planning tier without reading source files
- docs/config mismatches are detectable automatically

E5 completion note:

- E5 is now complete: planner-tier agents are visible in primary docs, linked-worktree reservation examples exist, default-agent guidance matches config, and automated doctor checks catch drift in inventory/default-agent documentation.

### 2026-03-10 - E5-T1 and E5-T4 planner-tier visibility plus default-agent reconciliation

Current status: `done`

Findings:

- Promoted the planning-tier agents in `README.md` so `strategic-planner`, `ambiguity-analyst`, and `plan-critic` are visible in the main agent inventory.
- Reconciled default-agent guidance with actual config: `build` remains the configured default in `opencode.json`, while `orchestrator` is documented as the preferred choice for larger multi-step execution.
- Corrected the active operating contract so it no longer claims `orchestrator` is the configured default.

Primary evidence references:

- `README.md`
- `instructions/agent_operating_contract.md`
- `opencode.json`

Validation:

- `python3 -m py_compile scripts/*.py && make validate`
- fresh `opencode run` smoke: `e5-default-agent-smoke` -> `PASS`

### 2026-03-10 - E5-T3 and E5-T5 planner reservation examples plus drift checks

Current status: `done`

Findings:

- Added a concrete planner-plus-reservation example in `docs/agents-playbook.md` that pairs planner agents with linked-worktree execution and explicit reservation setup/clear steps.
- Extended `scripts/agent_doctor.py` so it now checks for planner-tier visibility in `README.md` and default-agent wording alignment in `instructions/agent_operating_contract.md`.

Primary evidence references:

- `docs/agents-playbook.md`
- `scripts/agent_doctor.py`

Validation:

- `python3 scripts/agent_doctor.py run --json`
- `python3 -m py_compile scripts/*.py && make validate`
- fresh `opencode run` smoke: `e5-planner-smoke` -> `PASS`

### E6 Parity scoreboard and drift checks

Status: `done`

- [x] E6-T1 Create a focused parity scoreboard covering runtime parallelism, task graphing, agent visibility, and orchestration UX.
- [x] E6-T2 Mark intentional divergences versus true parity gaps so the roadmap does not become cargo-cult cloning.
- [x] E6-T3 Add doctor or validation checks for known drift risks: default agent docs, agent inventory docs, and runtime capability claims.
- [x] E6-T4 Keep this roadmap linked to implementation evidence, validation results, and follow-up backlog.

Definition of done:

- parity progress is visible without re-running a repo-wide audit
- intentional divergence is explicit
- claims in docs stay aligned with actual runtime behavior

E6 completion note:

- E6 is now complete: `docs/parity-scoreboard.md` gives one fast parity view, `docs/upstream-divergence-registry.md` captures intentional differences, validation checks scoreboard presence, and this roadmap links the implementation evidence and smoke results.

### 2026-03-10 - E6 parity scoreboard and drift checks

Current status: `done`

Findings:

- Added `docs/parity-scoreboard.md` as the one-screen parity summary with completed areas, intentional divergences, and drift-watch reminders.
- Extended `scripts/hygiene_drift_check.py` to fail if the scoreboard is missing or loses its required sections.
- Validation and fresh `opencode run` smoke both confirm the scoreboard and drift-check path are operational.

Primary evidence references:

- `docs/parity-scoreboard.md`
- `docs/upstream-divergence-registry.md`
- `scripts/hygiene_drift_check.py`

Validation:

- `python3 scripts/hygiene_drift_check.py`
- `python3 scripts/agent_doctor.py run --json`
- `python3 -m py_compile scripts/*.py && make validate`
- fresh `opencode run` smoke: `e6-scoreboard-smoke` -> `PASS`

## Suggested Delivery Order

1. E1 Runtime fan-out completion
2. E2 Dependency-aware execution graph
3. E3 Agent pool and background runtime hardening
4. E4 Orchestrator direction and model routing upgrades
5. E5 Planning tier productization
6. E6 Parity scoreboard and drift checks

## Notes For Implementation

- Reuse the active work in `docs/plan/parallel-subagent-fanout-roadmap.md` instead of opening a second parallel runtime track.
- Treat reservations as a core competitive advantage; upstream-style concurrency should be added on top of them, not instead of them.
- Keep command sprawl under control: prefer deeper behavior in `/workflow`, `/autoflow`, `/autopilot`, and `/agent-pool` before adding new slash commands.
- When a parity feature conflicts with local safety posture, bias toward local safety and record the divergence explicitly.

## First Slice Recommendation

Start with E1-T1 through E1-T3.

Why this slice first:

- it addresses the highest-confidence parity gap
- it unlocks the rest of the roadmap
- it gives us hard runtime evidence before we redesign higher-level orchestration docs or commands

## Working Notes

### 2026-03-09 - E1-T1 initial blocker trace

Current status: `doing`

Findings:

- The roadmap is already in the canonical planning location: `docs/plan/`.
- The likely residual blocker is still at the `tool.execute.before` to `tool.execute.after` boundary for `task`-based subagent launches.
- Launch-side metadata is injected correctly, but cleanup paths still permit fallback matching when structured identity is missing.
- When overlapping same-session delegations lose exact identity on the way out, cleanup can ambiguity-skip and leave stale running or reserved state behind.
- The next launch can then hit the familiar false blocker path: `Blocked delegation: subagent session ... is already running ...`.

Primary evidence references:

- `plugin/gateway-core/src/index.ts:855`
- `plugin/gateway-core/src/index.ts:934`
- `plugin/gateway-core/src/hooks/shared/delegation-trace.ts:121`
- `plugin/gateway-core/src/hooks/shared/delegation-trace.ts:134`
- `plugin/gateway-core/src/hooks/delegation-concurrency-guard/index.ts:146`
- `plugin/gateway-core/src/hooks/delegation-concurrency-guard/index.ts:191`
- `plugin/gateway-core/src/hooks/subagent-lifecycle-supervisor/index.ts:156`
- `plugin/gateway-core/src/hooks/subagent-lifecycle-supervisor/index.ts:365`

Immediate next slice:

- add one focused repro or selftest covering same-session same-type fan-out with missing `tool.execute.after` metadata
- capture which guard blocks next launch and which audit reason code fires
- then make `childRunId` and structured lifecycle identity mandatory for cleanup authority

Progress update:

- Added a focused repro selftest in `plugin/gateway-core/test/subagent-lifecycle-supervisor-hook.test.mjs`.
- The repro confirms the current blocker path is lifecycle-based: ambiguous cleanup leaves a running entry behind, and a relaunch using the same delegation trace hits `subagent_lifecycle_duplicate_running_blocked`.
- Targeted validation passed with `node --test test/subagent-lifecycle-supervisor-hook.test.mjs`.

### 2026-03-09 - E1-T2 and E1-T3 structured identity slice

Current status: `doing`

Findings:

- `childRunId` is now normalized to the canonical `subagent-run/<traceId>` shape when delegation metadata is read or stamped.
- Concurrency and lifecycle cleanup now require structured `childRunId` authority instead of falling back to session/subagent matching on `tool.execute.after`.
- When after-event identity is missing, hooks skip cleanup and emit explicit missing-identity audits instead of guessing.
- Existing telemetry coverage now also checks malformed `childRunId` normalization.

Primary evidence references:

- `plugin/gateway-core/src/hooks/shared/delegation-trace.ts`
- `plugin/gateway-core/src/hooks/delegation-concurrency-guard/index.ts`
- `plugin/gateway-core/src/hooks/subagent-lifecycle-supervisor/index.ts`
- `plugin/gateway-core/test/delegation-concurrency-guard-hook.test.mjs`
- `plugin/gateway-core/test/subagent-lifecycle-supervisor-hook.test.mjs`
- `plugin/gateway-core/test/runtime-delegation-hooks.test.mjs`

Validation:

- `npm run build && node --test test/subagent-lifecycle-supervisor-hook.test.mjs test/delegation-concurrency-guard-hook.test.mjs test/runtime-delegation-hooks.test.mjs`
- Result: pass (`35` tests, `0` failures)

Immediate next slice:

- inspect whether shared delegation runtime-state cleanup should also drop remaining subagent/session fallback paths
- verify same-session multi-agent behavior through the full gateway/plugin path beyond the current targeted suites

### 2026-03-09 - E1 runtime-state and runner-boundary follow-up

Current status: `doing`

Findings:

- Shared delegation runtime state now also keys active work by structured `childRunId` only.
- Outcome registration and active-clear paths no longer guess by trace, subagent type, or lone session entry when after-event identity is missing.
- The fuller `GatewayCorePlugin` integration path confirms child-run metadata survives the before/after runner boundary and supports out-of-order completion.
- Telemetry now intentionally drops outcome recording when after-event identity is missing instead of inventing a match.

Primary evidence references:

- `plugin/gateway-core/src/hooks/shared/delegation-runtime-state.ts`
- `plugin/gateway-core/test/runtime-delegation-hooks.test.mjs`
- `plugin/gateway-core/test/delegation-concurrency-guard-hook.test.mjs`

Validation:

- `npm run build && node --test test/delegation-concurrency-guard-hook.test.mjs test/runtime-delegation-hooks.test.mjs test/subagent-lifecycle-supervisor-hook.test.mjs`
- Result: pass (`37` tests, `0` failures)

Immediate next slice:

- broaden from targeted gateway-core coverage to one higher-level runtime flow if we want end-to-end CLI confidence
- decide whether any telemetry consumers need explicit missing-identity diagnostics surfaced beyond current audit events

### 2026-03-09 - Live same-session relaunch smoke and legacy cleanup

Current status: `doing`

Findings:

- A live CLI smoke using the current gateway-core runtime completed the old failure pattern successfully: two same-session `explore` subagents ran in parallel, then a third same-session `explore` subagent launched after the parallel wave without hitting an `already running` or duplicate-running blocker.
- The smoke used a temporary sync of the worktree `gateway-core/dist` files into the configured live plugin path, with hash evidence captured before and during execution.
- The live smoke returned `PASS`, with two parallel `task` completions followed by a third same-session `task` completion.
- Legacy compatibility was reduced where the structured identity path is now clearly authoritative: shared runtime-state no longer exposes unused fallback-match inputs, telemetry no longer passes those stale fields, and delegation metadata reading no longer accepts top-level `metadata.delegation`.
- Canonical trace-to-child-run normalization remains in place and is still intentional.

Primary evidence references:

- CLI smoke output: `/tmp/gwcfglive/parallel-relaunch.stdout`
- CLI smoke logs: `/tmp/gwcfglive/parallel-relaunch.stderr`
- CLI smoke hash manifest: `/tmp/gwcfglive/parallel-relaunch-hashes.json`
- `plugin/gateway-core/src/hooks/shared/delegation-runtime-state.ts`
- `plugin/gateway-core/src/hooks/shared/delegation-trace.ts`
- `plugin/gateway-core/src/hooks/subagent-telemetry-timeline/index.ts`

Validation:

- `npm run build && node --test test/runtime-delegation-hooks.test.mjs test/delegation-concurrency-guard-hook.test.mjs test/subagent-lifecycle-supervisor-hook.test.mjs`
- Result: pass (`37` tests, `0` failures)
- Live smoke result: pass (`PASS` from fresh session flow)

Immediate next slice:

- decide whether to formalize the live relaunch smoke into selftest/install-smoke coverage
- if so, add a non-interactive harness that can safely swap or inject the local gateway plugin path without touching user config

### 2026-03-09 - Automation harness for live relaunch smoke

Current status: `doing`

Findings:

- Added a reusable non-interactive harness in `scripts/gateway_live_relaunch_smoke.py` that can temporarily sync selected `gateway-core/dist` files into the installed plugin path, run the same-session relaunch smoke, capture artifact paths and hash evidence, and restore the installed copy afterward.
- Integrated that harness into `make install-test` so the installer smoke now covers the live parallel-wave-then-relaunch path under an isolated temp `HOME` and `XDG_CACHE_HOME`.
- Added deterministic selftest coverage for the harness by stubbing `opencode`, asserting PASS output, emitted artifacts, and restoration of the installed plugin dist files.

Primary evidence references:

- `scripts/gateway_live_relaunch_smoke.py`
- `Makefile:132`
- `scripts/selftest.py:3460`

Validation:

- `python3 -m py_compile scripts/*.py && make install-test`
- `npm run build && node --test test/runtime-delegation-hooks.test.mjs test/delegation-concurrency-guard-hook.test.mjs test/subagent-lifecycle-supervisor-hook.test.mjs`

Immediate next slice:

- consider whether this harness should also be callable from `scripts/selftest.py` against a real installed tree in CI
- if install-smoke runtime is acceptable, keep selftest deterministic and let install-test remain the canonical live relaunch verification path

### 2026-03-09 - E1-T5 stress matrix coverage

Current status: `doing`

Findings:

- Extended runtime delegation stress coverage from a single 5-subagent case into a `2, 3, 4, 5` same-session matrix with mixed subagent types and varied completion ordering.
- Each scenario now asserts exact outcome count, unique `childRunId` values, preserved mixed `subagentType` coverage, completed status for all outcomes, and a successful same-session follow-up launch after the wave.
- Kept the first implementation at the hook-composition layer because it exercises concurrency, lifecycle, and telemetry together with less wrapper noise than a plugin-level matrix.

Primary evidence references:

- `plugin/gateway-core/test/runtime-delegation-hooks.test.mjs:19`
- `plugin/gateway-core/test/runtime-delegation-hooks.test.mjs:432`

Validation:

- `npm run build && node --test test/runtime-delegation-hooks.test.mjs test/delegation-concurrency-guard-hook.test.mjs test/subagent-lifecycle-supervisor-hook.test.mjs`
- Result: pass (`40` tests, `0` failures)

Immediate next slice:

- re-run one linked-worktree protected-main scenario for E1-T6 so the new stress coverage is paired with a safety-regression check
- optionally add a single plugin-level sentinel if we want one more wrapper-path assertion beyond the hook matrix

### 2026-03-09 - E1-T6 linked-worktree protected-main safety check

Current status: `done`

Findings:

- Re-ran the existing protected-`main` linked-worktree safety sentinels at the gateway hook layer after the E1 identity and stress-matrix work.
- Confirmed `apply_patch` and linked-target command paths remain allowed when the session directory is the protected primary `main` worktree but the actual target is a linked worktree.
- This keeps the core local advantage intact: protected `main` stays edit-blocked while linked worktrees remain the valid mutation surface.

Primary evidence references:

- `plugin/gateway-core/test/workflow-conformance-guard-hook.test.mjs:203`
- `plugin/gateway-core/test/workflow-conformance-guard-hook.test.mjs:383`

Validation:

- `npm run build && node --test --test-name-pattern="workflow-conformance-guard allows apply_patch targeting a linked worktree from protected main|workflow-conformance-guard allows linked worktree targets when session directory is protected main" test/workflow-conformance-guard-hook.test.mjs`
- Result: pass (`2` tests, `0` failures)

E1 completion note:

- E1 is now complete: blocker trace, structured child-run identity, legacy fallback removal, stress coverage, live same-session smoke, and protected-`main` linked-worktree safety checks are all in place.

### 2026-03-09 - E2-T1 shared task-graph schema wiring

Current status: `done`

Findings:

- Reused the existing shared `task_graph.json` runtime instead of introducing a second graph store, and added a thin bridge that projects canonical `/workflow` runs into durable task nodes.
- Workflow runs and resumes now update stable graph node ids derived from workflow path plus step id, preserving `blockedBy`, `blocks`, `owner`, execution metadata, and a reusable shared `task_graph_path` in command output.
- Added shared graph-path references to canonical `/autoflow` and `/autopilot` status/report surfaces so downstream orchestration can point at the same durable graph location while deeper scheduler work remains pending.
- Selftest now verifies the end-to-end slice: completed workflow runs leave no ready tasks, failed runs expose the failed step as the ready lane while keeping downstream conditional steps blocked, and resume clears the ready lane again using the same shared graph path.

Primary evidence references:

- `scripts/task_graph_runtime.py`
- `scripts/task_graph_bridge.py`
- `scripts/workflow_command.py`
- `scripts/start_work_command.py`
- `scripts/autopilot_command.py`
- `scripts/selftest.py`
- `docs/specs/e8-plan-handoff-continuity-mapping.md:14`

Validation:

- `python3 -m py_compile scripts/*.py && make selftest`
- Result: pass

Decision note:

- E2-T1 source of truth stays in shared runtime storage via `task_graph.json`; command-specific runtimes remain local execution metadata stores that can reference the shared graph.

Immediate next slice:

- formalize E2-T2 by documenting shared-runtime authority versus command-local metadata and wiring `/workflow status` plus `/task ready` into a clearer operator contract
- then move into E2-T3 runnable-lane scheduling/reporting on top of the shared graph

### 2026-03-09 - E2-T2 shared-runtime authority contract

Current status: `done`

Findings:

- Documented the source-of-truth decision explicitly: shared runtime storage via `task_graph.json` is authoritative for dependency state.
- Clarified that `/workflow` writes dependency projections into the shared graph, while `/autoflow` and `/autopilot` retain only command-local lifecycle metadata and expose `task_graph_path` as a reference.
- Updated command contracts and continuity spec so operators and future implementation slices have one documented dependency-store model.

Primary evidence references:

- `instructions/autoflow_command_contract.md`
- `instructions/autopilot_command_contract.md`
- `docs/specs/e8-plan-handoff-continuity-mapping.md`

Validation:

- `make validate`
- `make selftest`

Immediate next slice:

- implement E2-T3 runnable-lane scheduling/reporting so shared graph readiness becomes actionable concurrency output rather than only persisted state

### 2026-03-09 - E2-T3 runnable lanes and blocked reporting

Current status: `done`

Findings:

- Added runnable-lane and blocked-task analysis directly on top of the shared task graph runtime instead of creating a separate scheduler state store.
- `/task ready --json` now returns `runnable_lanes`, `blocked`, and `summary` alongside the existing compatibility `tasks` list.
- Canonical command surfaces now expose the shared task graph snapshot so `/workflow`, `/autoflow`, and `/autopilot` can report ready lanes and blocked reasons from the same underlying graph.
- Tightened workflow semantics so dry-run runs do not mutate the shared graph, explicit dependencies gate execution, and skipped tasks remain terminal dependencies instead of becoming false-ready work.
- Fresh `opencode run` smoke confirmed the intended operator path: a temporary graph with tasks `A`, `B <- A`, and `C` produced `lane_count == 2`, blocked task `B`, and ready tasks `A` and `C`.
- Added follow-up fan-in coverage so a join task like `D <- A,C` does not appear inside runnable lanes until both parents are satisfied.
- Added conditional-prefix coverage so implicit `on_success` / `on_failure` graph dependencies now wait on the full settled prefix, not only the immediately previous step.
- Added mixed explicit-dependency plus conditional coverage so `depends_on` does not weaken prefix-wide `on_success` / `on_failure` gating in the shared graph.
- Kept `/workflow` dry-run responses from claiming a shared graph snapshot they did not mutate, and preserved failure-specific blocked reasons for downstream tasks in execute-mode projections.

Primary evidence references:

- `scripts/task_graph_runtime.py`
- `scripts/task_graph_command.py`
- `scripts/task_graph_bridge.py`
- `scripts/workflow_command.py`
- `scripts/start_work_command.py`
- `scripts/autopilot_command.py`
- `scripts/selftest.py`
- `/tmp/e2-task-graph-smoke-4.stdout`

Validation:

- `python3 -m py_compile scripts/*.py && make selftest && make validate`
- fresh `opencode run` smoke: `e2-task-graph-smoke-4` -> `PASS`

Immediate next slice:

- implement E2-T4 reservation-aware lane scheduling so runnable lanes can be filtered by writer ownership and disjoint-path safety
- then add E2-T5 status/report refinements for clearer operator-facing lane and blocked-reason summaries

### 2026-03-09 - E2-T4 reservation-aware lane scheduling kickoff

Current status: `done`

Findings:

- The smallest E2-T4 slice should stay in Python task-graph runtime code and mirror the existing gateway reservation guard rather than inventing a second reservation model.
- Current task graph nodes do not yet carry reservation/write-path metadata, so reservation-aware filtering needs task metadata such as `metadata.reservation_paths` before lanes can be safely filtered.
- The clearest first test path is the direct task-graph block in `scripts/selftest.py`, seeded with raw task graph fixtures plus `.opencode/reservation-state.json` fixtures.

Completion update:

- Added reservation-aware filtering directly in the shared task graph runtime so ready tasks and runnable lanes now honor owned-path coverage and active-path conflicts.
- Added task metadata support for `reservation_paths` in `/task` command mutations and workflow graph projection.
- Verified with selftest/validate plus a fresh `opencode run` smoke that only owned non-conflicting lanes remain runnable while conflict and uncovered lanes surface explicit reservation reasons.

Primary evidence references:

- `scripts/task_graph_runtime.py`
- `scripts/task_graph_command.py`
- `scripts/task_graph_bridge.py`
- `scripts/selftest.py`
- `/tmp/e2-reservation-lane-smoke-5.stdout`

Validation:

- `python3 -m py_compile scripts/*.py && make selftest && make validate`
- fresh `opencode run` smoke: `e2-reservation-lane-smoke-5` -> `PASS`

Immediate next slice:

- implement E2-T5 so status/report surfaces present clearer operator-facing lane summaries and blocked-reason rollups
- then move to E2-T6 recovery/resume coverage for interrupted graph state

### 2026-03-10 - E2-T5 status/report graph snapshots

Current status: `done`

Findings:

- `/task ready --json` now exposes reservation-aware ready tasks plus `runnable_lanes`, `blocked`, and `summary`.
- `/workflow`, `/autoflow`, and `/autopilot` status/report surfaces all reference the same shared graph snapshot instead of diverging per-command payloads.
- Validation/doctor output now reports reservation-aware ready counts so health checks agree with the actually schedulable set.

Primary evidence references:

- `scripts/task_graph_command.py`
- `scripts/workflow_command.py`
- `scripts/start_work_command.py`
- `scripts/autopilot_command.py`

### 2026-03-10 - E2-T6 interrupted-run and resume coverage

Current status: `done`

Findings:

- Added partial workflow-state persistence so execute-mode runs can publish active progress and shared graph snapshots after each settled step.
- Added deterministic interruption coverage using `MY_OPENCODE_WORKFLOW_INTERRUPT_AFTER_STEP`, allowing interrupted runs to remain resumable without inventing a second recovery store.
- `/workflow resume` now accepts interrupted runs, `/autopilot resume` and `/start-work recover` now expose shared task graph snapshots, and selftest verifies active interrupted state plus successful completion after resume.

Primary evidence references:

- `scripts/workflow_command.py`
- `scripts/autopilot_command.py`
- `scripts/start_work_command.py`
- `scripts/selftest.py`
- `/tmp/e2-recovery-smoke-2.stdout`

Validation:

- `python3 -m py_compile scripts/*.py && make selftest && make validate`
- fresh `opencode run` smoke: `e2-recovery-smoke-2` -> `PASS`

E2 completion note:

- E2 is now complete: shared graph schema, source-of-truth contract, runnable-lane scheduling, reservation-aware filtering, operator-facing snapshots, and recovery/resume coverage are all in place.

Primary evidence references:

- `scripts/task_graph_runtime.py`
- `scripts/task_graph_bridge.py`
- `scripts/reservation_command.py`
- `plugin/gateway-core/src/hooks/parallel-writer-conflict-guard/index.ts`
