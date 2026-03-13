# Current Roadmap Tracker

Tracks the active `my_opencode` improvement wave so any AI can recover context quickly.

## Working Rules

- Keep the primary repo on `main`.
- Start each new implementation task in a dedicated worktree branch from the current root branch.
- Treat canonical commands as the source of truth; do not reintroduce legacy aliases without a clear migration reason.
- When a workflow is changed, align docs, health checks, and selftests in the same slice.

## Status Legend

- pending
- doing
- done
- blocked

## Active PRs

None for this wave right now. Most recent merges are `#406`, `#409`, and `#414`.

## Current Epics

### E1 Canonical Command Unification

Status: doing

Goal:
- converge overlapping slash-command behavior into a single canonical surface that docs, `/doctor`, and selftests all share

Delivered:
- simplified slash-command surface
- reduced routing/quality command overlap
- merged policy and keyword controls into canonical commands
- aligned doctor checks with canonical command paths
- restored canonical plan-flow command
- refreshed canonical workflow docs and operator guidance

Remaining:
- review for any lingering duplicate surfaces or outdated docs references
- keep future features on canonical commands only

### E2 Worktree-First Runtime Enforcement

Status: doing

Goal:
- stop agents from editing the primary `main` worktree and reinforce full worktree lifecycle behavior

Delivered:
- main/worktree guard work landed in earlier slices
- current operator guidance now assumes worktree-first execution

Remaining:
- keep validating that runtime guards still push agents into the right worktree flow
- document any edge cases discovered during real sessions

### E3 Continuation and Parallel Orchestration Hardening

Status: doing

Goal:
- improve continuation reliability, subagent routing, and parallel execution discipline

Delivered:
- continuation enforcement and reminder hooks were added in prior waves
- delegation/routing/runtime guidance was strengthened

Remaining:
- continue reviewing where agents still stop too early or fail to parallelize safe work
- keep model/effort routing aligned with task class

### E4 Model Routing Integration

Status: done

Goal:
- auto-wire model-routing resolution into normal execution entrypoints without leaking transient routing metadata into persisted state

Delivered:
- entrypoint routing integration implemented
- response-level routing metadata added to relevant outputs
- persistence leakage prevented
- routing selftests expanded
- PR `#406` merged

Remaining:
- monitor for regressions as new command/runtime slices land

### E5 Selftest and Doctor Stabilization

Status: done

Goal:
- keep validation green as canonical-command and routing changes land

Delivered:
- fixed layered config discovery for post-session digest execution
- switched forced auto-slash execute coverage to a stable dispatch path
- corrected auto-slash precision accounting
- PR `#409` merged

Remaining:
- watch for unrelated selftest drift after future main-branch guard updates

### E6 Roadmap Memory and Handoff Tracking

Status: done

Goal:
- keep a durable roadmap note with epics, active work, and handoff-ready next tasks

Delivered:
- added tracker at `docs/plan/current-roadmap-tracker.md`
- PR `#414` merged

Remaining:
- keep this tracker updated at each milestone boundary

### E7 Shared Memory, Swarm, Plugin Platform, and Ops Automation

Status: doing

Goal:
- close the next high-value platform gaps with local shared memory first, then current-runtime swarm coordination, plugin-pack extensibility, and deterministic ops automation

Delivered:
- opened execution tracker at `docs/plan/e13-shared-memory-swarm-plugin-ops-plan.md`
- shipped initial `/memory` baseline with local SQLite storage, lexical retrieval, recall, pinning, summarization, doctor integration, and selftests
- added `/memory promote` for digest, session, workflow, claims, and doctor-report artifact promotion into shared memory
- converged `/memory-lifecycle` admin flows onto the same shared-memory SQLite runtime
- started the swarm prototype with `/workflow swarm` planning/status/doctor/close on top of current workflow, claims, agent-pool, and reservation contracts
- extended the swarm prototype with `/workflow swarm handoff` and `/workflow swarm rebalance` for safe lane mutation
- added the first swarm execution bridge with `/workflow swarm accept-handoff` and controlled `/bg` enqueueing for allowed commands
- added explicit lane completion/failure transitions and swarm-level progress summaries
- added follow-up guidance plus deterministic auto-progression of the next planned lane when no lane remains active
- added explicit failure-recovery policy output and conservative single-active-lane coordination rules
- added executable recovery actions (`reset-lane`, `retry-lane`) and conservative ordered coordination with surfaced read-only parallel capacity
- added recommended recovery decisions and `resolve-failure` execution on top of reset/retry recovery flows
- added explicit lane dependency metadata and dependency-aware activation/failure blocking logic
- added `--graph-file` support for custom swarm lane graphs with validation
- added explicit reservation-safe read metadata and enabled dependency-satisfied parallel activation for read-only lanes when reservation guarantees are present
- added explicit lane `path_scopes` and overlap-aware coordination checks
- added lease-backed writer guarantee diagnostics and surfaced disjoint write parallel candidates
- enabled a tiny lease-backed write-capable parallel allowlist for disjoint `implement` lanes
- added lane-level `lease_identity` metadata and enforced it for writer activation
- started E4 ops automation readiness diagnostics with `/ship doctor` and umbrella `/doctor` coverage for canonical issue/PR/release/hotfix flows
- added canonical `/delivery` handoff summaries to `/ship doctor` and `/ship create-pr --issue <id>` template generation
- added latest-closure follow-up linkage auditing to `/hotfix doctor` so umbrella diagnostics can surface incident follow-up drift

Remaining:
- broaden write-capable parallelism beyond the tiny `implement` allowlist only when stronger lane-level lease identity and ownership guarantees exist
- deepen E4 from readiness diagnostics into higher-touch issue/PR/release/hotfix workflow automation without introducing overlapping command surfaces

## Doing Now

| Item | Status | Notes |
|---|---|---|
| Post-merge guard behavior verification | doing | Validate protected-main behavior in real operator flows after `#423`. |
| Canonical guidance drift watch | doing | Keep active docs canonical-first as command/runtime surfaces evolve. |
| LLM decision hooks planning | doing | Active plan lives under `docs/plan/status/in_progress/llm-decision-hooks-plan.md`; current checkpoint includes refreshed rollout guidance, passing semantic/workflow scenario coverage, and completed `task-resume-info` plus `mistake-ledger` rollout-evidence reconciliation on top of the shared runtime. |
| Post-merge parity backlog triage | doing | Active backlog lives in `docs/plan/post-merge-parity-backlog-2026-03-10.md`; use it to sequence remaining divergence decisions and any reopened parity slices. |
| Parity hardening follow-up | doing | Fix crossed LLM decision hook bindings, add safe hook startup isolation, and keep remaining upstream runtime deltas explicit in parity docs. |
| Atlas runtime prototype | doing | Prototype local post-task verification/reminder shaping through `task-resume-info` without importing full Atlas persona semantics. |
| Atlas pre-task shaping prototype | doing | Add delegated task focus shaping through `agent-context-shaper` before subagent execution. |
| AI-native autopilot orchestration design | doing | New design plan in `docs/plan/ai-native-autopilot-orchestration-plan.md` proposes autonomous task claims, same-worktree write leases, hard completion gates, policy injection, and retry routing for lower-touch autopilot execution; first execution slice now lives in `docs/plan/ai-autopilot-completion-gates-execution-plan.md` and is intentionally `/autopilot` + shared task-metadata first, with `/autoflow` convergence documented as follow-up adoption work rather than current-slice behavior. |
| Gateway E2E parity refinements | doing | Tighten fail-closed behavior for critical hooks, isolate hook execution failures, align continuity wording with canonical commands, and remove hard-coded agent metadata discovery. |
| E13 lane lease identity | doing | Active implementation tracker lives at `docs/plan/e13-shared-memory-swarm-plugin-ops-plan.md`; current slice adds lane-level lease identity to writer activation. |
| E13 ops automation readiness diagnostics | doing | First E4 slice adds `/ship doctor`, umbrella `/doctor` coverage, and refreshed handbook/quickstart guidance so canonical issue/PR/release/hotfix automation can be audited before deeper automation lands. |

## Done Recently

| Item | Status | Notes |
|---|---|---|
| Reconstructed current initiative from git/OpenCode history | done | Reviewed reflog, prompt history, logs, and checkpoints. |
| Merged model routing entrypoint PR | done | `#406` merged after refresh-from-main and CI pass. |
| Merged selftest follow-up PR | done | `#409` merged after refresh-from-main and CI pass. |
| Orchestration reliability hardening wave documented | done | Fresh-session continuation summary now lives in `docs/plan/status/in_progress/orchestration-reliability-continuation-2026-03-10.md`, covering merged PRs `#442`, `#446`, `#449`, `#451`, and `#454`. |
| Merged roadmap tracker PR | done | `#414` merged after branch freshness refresh and CI pass. |
| Merged canonical docs guidance PR | done | `#419` merged after CI pass and branch refresh. |
| Merged workflow resume/runtime guard PR | done | `#420` merged after CI success. |
| Merged E2/E3 guard hardening slice | done | `#423` merged with chained protected-command parsing and branch-freshness fallback guidance updates. |
| Final canonical active-doc sweep complete | done | Active operator docs now keep compatibility aliases explicitly secondary. |
| Synced local `main` while preserving local docs edit | done | Used targeted stash + `git pull --rebase` + stash pop for `docs/plan/docs-automation-summary.md`. |
| Reviewed parity plan against upstream runtime behavior | done | Identified crossed hook LLM bindings, missing safe hook creation, and remaining intentional divergence around Atlas runtime injection and Claude compatibility hooks. |
| Committed parity hardening gateway fixes | done | Created `55ad23f` to fix LLM hook bindings, add safe hook startup isolation, and refresh parity tracking evidence. |
| Committed Atlas post-task reminder prototype | done | Created `fa270cf` to add local verification/reminder shaping for delegated task results. |
| Committed Atlas pre-task shaping prototype | done | Created `d090f80` to prepend delegated task focus guidance before subagent execution. |
| Merged parity hardening and atlas shaping PR | done | `#443` merged to `main`, including E2E gateway hook-failure hardening in `b9a7f05`. |
| Normalized parity tracker after merge | done | Replaced merged parity execution slices with a single post-merge backlog triage stream and moved remaining decisions into `docs/plan/post-merge-parity-backlog-2026-03-10.md`. |
| Reviewed `claude-code-hooks` compatibility divergence | done | Captured keep-closed decision in `docs/plan/claude-code-hooks-decision-2026-03-11.md` unless direct Claude transcript/session compatibility becomes a real requirement. |
| Refined direct-work discipline documentation exceptions | done | `direct-work-warning` now supports configurable allowlisted docs paths across relative, absolute, `apply_patch`, and `multiedit` payloads while staying warn-first by default. |

## Next Tasks

<<<<<<< HEAD
1. Continue post-merge verification for protected-main guard behavior in real operator flows.
2. Monitor branch-freshness guard fallbacks in live PR merge/update workflows.
3. Keep active docs canonical-first as new command/runtime slices land.
4. Accumulate a fresh live disagreement window, then rerun rollout reporting before promoting `delegation-fallback-orchestrator`; keep `todo-continuation-enforcer`, `task-resume-info`, `mistake-ledger`, and `validation-evidence-ledger` in shadow until then.
5. Expand the semantic decision inventory so every ambiguous classification path is tracked by `done` / `doing` / `pending` status band.
6. Decide whether direct-work discipline should remain warn-first by default or gain a broader escalation policy.
7. Convert the AI-native autopilot design into a first execution slice, starting with completion-gate unification plus machine-readable task ownership.
8. Keep this tracker and the CLI todo list synchronized at each task handoff.
=======
1. Continue E7/E13 by strengthening lane-level lease identity/ownership guarantees before broadening write-capable parallelism beyond the tiny implement-lane allowlist.
2. Continue post-merge verification for protected-main guard behavior in real operator flows.
3. Monitor branch-freshness guard fallbacks in live PR merge/update workflows.
4. Keep active docs canonical-first as new command/runtime slices land.
5. Keep this tracker and the CLI todo list synchronized at each task handoff.
>>>>>>> 551182d (Build local shared-memory and swarm execution foundation)

## Handoff Notes

- Before starting new implementation, re-check that local `main` matches the latest remote `main`.
- Use a dedicated worktree for each new slice, even for docs/tracking follow-ups.
- Keep the CLI todo list and this tracker aligned: epics here, active steps in the runtime todo list.
- For the platform wave, use `docs/plan/e13-shared-memory-swarm-plugin-ops-plan.md` as the source of truth for E7/E13 execution status.
