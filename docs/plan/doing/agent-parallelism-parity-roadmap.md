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
| E1 Runtime fan-out completion | P0 | backlog | remove remaining same-session subagent launch blockers | task runner, gateway, lifecycle hooks |
| E2 Dependency-aware execution graph | P0 | backlog | schedule independent work in parallel with explicit dependencies | `/workflow`, `/autoflow`, task state |
| E3 Agent pool and background runtime hardening | P1 | backlog | make runtime worker management concrete, observable, and trustworthy | `/agent-pool`, `/bg`, runtime state |
| E4 Orchestrator direction and model routing upgrades | P1 | backlog | make orchestration prompts and routing sharper for parallel execution | `agent/orchestrator.md`, routing policy |
| E5 Planning tier productization | P1 | backlog | elevate planner/ambiguity/critic roles into normal operator flows | README, docs, command guidance |
| E6 Parity scoreboard and drift checks | P2 | backlog | track parity progress and prevent docs/config drift | docs, doctor checks, parity trackers |

## Epics And Tasks

### E1 Runtime fan-out completion

Status: `backlog`

- [ ] E1-T1 Trace the remaining runner-boundary blocker behind same-session second-subagent failures and document the exact failure path.
- [ ] E1-T2 Introduce a stable child run identifier for every delegated subagent execution, separate from parent session id.
- [ ] E1-T3 Require structured delegation lifecycle payloads for launch, running, completion, and cleanup paths.
- [ ] E1-T4 Remove the remaining prompt/output parsing fallbacks where structured identity is available.
- [ ] E1-T5 Add stress coverage for `2-5` concurrent subagents with varied completion ordering and mixed subagent types.
- [ ] E1-T6 Re-run linked-worktree protected-main scenarios to confirm no regression in safety guard behavior.

Definition of done:

- same-session mixed fan-out succeeds reliably
- same-session same-type fan-out succeeds reliably
- follow-up delegation after a parallel wave does not false-block
- live results remain reservation-safe and linked-worktree-safe

### E2 Dependency-aware execution graph

Status: `backlog`

- [ ] E2-T1 Define a durable task graph schema for canonical local flows with `blockedBy`, `blocks`, ownership, and execution state.
- [ ] E2-T2 Decide whether the source of truth belongs under `/workflow`, `/autoflow`, or shared runtime storage, then document the contract.
- [ ] E2-T3 Implement ready-task selection so independent tasks can run in parallel while blocked tasks wait deterministically.
- [ ] E2-T4 Integrate reservation awareness so schedulable work also respects disjoint writer ownership.
- [ ] E2-T5 Add JSON/status/report output showing graph state, blocked reasons, and runnable lanes.
- [ ] E2-T6 Add recovery/resume coverage for interrupted runs and partial completion states.

Definition of done:

- explicit task graphs can be created, resumed, and inspected
- independent lanes run concurrently when safe
- blocked tasks explain exactly why they are waiting
- reservation policy still overrides unsafe concurrency

### E3 Agent pool and background runtime hardening

Status: `backlog`

- [ ] E3-T1 Audit `/agent-pool` versus `/bg` responsibilities and choose a single clear runtime ownership model.
- [ ] E3-T2 Either deepen `/agent-pool` into real worker lifecycle management or narrow it to a thin observability facade.
- [ ] E3-T3 Add runtime health signals for spawn failures, stuck workers, queue depth, and stale sessions.
- [ ] E3-T4 Add parent-child evidence links so background results can be tied back to the initiating run and task graph node.
- [ ] E3-T5 Add `doctor` coverage and operator docs for restart, drain, cleanup, and failure triage.

Definition of done:

- runtime ownership is conceptually simple
- operator can tell what is running, blocked, failed, or stale
- background execution is observable enough to trust in day-to-day use

### E4 Orchestrator direction and model routing upgrades

Status: `backlog`

- [ ] E4-T1 Tighten `orchestrator` prompt guidance for intent routing, parallelism triggers, and when to stay single-writer.
- [ ] E4-T2 Add explicit guidance for task-graph-aware delegation: discover in parallel, implement in controlled lanes, validate before merge.
- [ ] E4-T3 Review model-routing defaults so parallel read-only loops, planning passes, and critical reviews use the right category consistently.
- [ ] E4-T4 Add concrete playbook examples showing when to use `explore`, `strategic-planner`, `ambiguity-analyst`, and `plan-critic` together.
- [ ] E4-T5 Add command-level guidance so `/autopilot` and `/autoflow` converge on the same orchestration mental model.

Definition of done:

- orchestrator behavior is sharper and less ambiguous
- planning roles are integrated into normal orchestration decisions
- runtime and docs tell the same story

### E5 Planning tier productization

Status: `backlog`

- [ ] E5-T1 Update README agent inventory so the planning specialist tier is visible and not buried.
- [ ] E5-T2 Update `docs/agents-playbook.md` and operator docs with recommended planner bundles for complex work.
- [ ] E5-T3 Add examples pairing planning agents with reservations and linked-worktree execution.
- [ ] E5-T4 Reconcile `default_agent` documentation with actual config and intended operator guidance.
- [ ] E5-T5 Add `agent-doctor` or catalog checks that flag inventory/documentation mismatches.

Definition of done:

- agent coverage is documented accurately
- users can discover the planning tier without reading source files
- docs/config mismatches are detectable automatically

### E6 Parity scoreboard and drift checks

Status: `backlog`

- [ ] E6-T1 Create a focused parity scoreboard covering runtime parallelism, task graphing, agent visibility, and orchestration UX.
- [ ] E6-T2 Mark intentional divergences versus true parity gaps so the roadmap does not become cargo-cult cloning.
- [ ] E6-T3 Add doctor or validation checks for known drift risks: default agent docs, agent inventory docs, and runtime capability claims.
- [ ] E6-T4 Keep this roadmap linked to implementation evidence, validation results, and follow-up backlog.

Definition of done:

- parity progress is visible without re-running a repo-wide audit
- intentional divergence is explicit
- claims in docs stay aligned with actual runtime behavior

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
