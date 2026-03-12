# E13 Shared Memory, Swarm, Plugin, and Ops Automation Plan

Date: 2026-03-10
Owner: OpenCode orchestrator
Status: doing

## Why this plan exists

Close the highest-value gaps found in the `claude-flow` comparison without copying its architecture blindly. Reuse the current `my_opencode` command surface, worktree-first operating model, `agents.md` discipline, Python slash-command backend, and `gateway-core` hook runtime.

## Owner decisions locked for this wave

- Shared memory must stay local-first and must not depend on external APIs.
- Shared memory must not require vector search.
- Swarm/coordinator features should extend the current software instead of introducing a second runtime.
- MCP expansion is out of scope for this wave.
- Plugin-platform improvements are in scope when they strengthen the current `gateway-core` model.
- Operations automation is a priority and should be optimized around existing `claims`, `workflow`, `delivery`, `daemon`, `doctor`, `release-train`, and agent contracts.

## Status legend

- pending
- doing
- done
- blocked

## Current foundations already done

- done: `claims` lifecycle, handoff, and stale-claim controls from `docs/plan/v0.5-productivity-parity-track.md`
- done: `workflow` engine, guarded execution, and DAG ordering from `docs/plan/v0.5-productivity-parity-track.md`
- done: `daemon` observability and agent-pool lifecycle from `docs/plan/v0.5-productivity-parity-track.md`
- done: `memory-lifecycle` export/import/compress/cleanup baseline from `docs/plan/v0.5-productivity-parity-track.md`
- done: worktree-first runtime enforcement and operator playbooks in `AGENTS.md`, `docs/operator-playbook.md`, and `docs/parallel-wt-playbook.md`
- done: single supported plugin runtime in `docs/plugin-gateway-plan.md`

## Quick board

| Epic | Priority | State | Goal | Depends on | Notes |
| --- | --- | --- | --- | --- | --- |
| E0 Plan scaffold and alignment | P0 | done | Lock scope, decisions, and execution order | - | This document is the control plane for the wave. |
| E1 Local shared memory runtime | P0 | doing | Add durable, smart shared memory without APIs or vector search | existing `memory-lifecycle` | Build retrieval with summaries, links, tags, FTS/BM25, and recency heuristics. |
| E2 Swarm coordination on current runtime | P0 | pending | Add first-class multi-agent coordination on top of `claims`, `workflow`, `agent-pool`, and reservations | E1 partial | No parallel second runtime; keep current slash-command model. |
| E3 Plugin platform expansion | P1 | pending | Turn `gateway-core` into a safer extension platform without MCP scope | E2 design | Favor hook packs, command packs, diagnostics, and policy contracts. |
| E4 Operations automation expansion | P0 | pending | Add richer issue/PR/release/incident automation aligned to `agents.md` | E2 partial | Optimize for deterministic workflows, handoff, and release hygiene. |

## Architecture principles for the wave

1. Prefer local durable state over hosted services.
2. Prefer deterministic retrieval over opaque embeddings.
3. Reuse canonical commands before adding new ones.
4. Keep `gateway-core` as the extension anchor.
5. Keep worktree-first and reservation-aware parallelism mandatory.
6. Treat every new capability as reviewable by `/doctor` and covered by selftests.
7. Add a new top-level command family only when extending an existing canonical family would be less clear or less safe.

## E1 Local shared memory runtime

Status: doing

### Outcome

Give agents and operators a durable shared memory they can query, summarize, prune, hand off, and reuse across sessions without vector databases or external APIs.

### Smart alternatives to vector search

- SQLite-backed memory store with FTS5 or BM25 lexical ranking for fast local retrieval.
- Structured memory records with `kind`, `scope`, `project`, `agent`, `task`, `tags`, `keywords`, `links`, `timestamp`, and `confidence` fields.
- Rolling summary layers: raw event -> condensed note -> topic summary -> handoff digest.
- Memory graph edges for `relates_to`, `blocks`, `decision_for`, `supersedes`, and `derived_from`.
- Recency + frequency + explicit pinning + reason-code weighting for ranking.
- Deterministic extractors that promote important command outputs, decisions, blockers, and validations into durable records.

### Canonical command decision

- Keep `/memory-lifecycle` for administrative operations such as stats, cleanup, compress, export, import, and doctor.
- Introduce `/memory` only for content-oriented shared-memory actions such as add, find, recall, link, summarize, and pin.
- Record `/memory` as a justified new canonical family because the user-facing mental model is different from lifecycle maintenance; no duplicate admin subcommands should be added under `/memory`.

### Proposed command surface

- `/memory add`
- `/memory find`
- `/memory recall`
- `/memory link`
- `/memory summarize`
- `/memory pin`
- keep archive/cleanup/doctor under `/memory-lifecycle`

### Detailed tasks

- [ ] E1-T1 Define the canonical memory schema, retention policy, and ranking contract.
- [ ] E1-T2 Reuse `memory-lifecycle` storage paths where possible and add lock-safe persistence.
- [ ] E1-T3 Implement lexical retrieval with FTS/BM25 plus deterministic score boosts for recency, pins, and graph links.
- [ ] E1-T4 Add promotion rules from digests, handoffs, workflow runs, claim history, and doctor findings.
- [ ] E1-T5 Add session and worktree scoping so memory can be local, repo-wide, or shared by explicit namespace.
- [ ] E1-T6 Add slash commands, JSON output, reason codes, and handbook docs.
- [ ] E1-T7 Add cleanup, archive, and compaction flows that preserve important summaries.
- [ ] E1-T8 Add selftests for retrieval quality, dedupe, stale memory handling, and corrupted-store recovery.

### Done criteria

- Agents can recall previous decisions and blockers across sessions using only local state.
- Handoff flows can retrieve concise context without replaying large raw histories.
- Ranking remains explainable and deterministic.
- `make selftest`, `make validate`, and `doctor` checks cover the new storage/runtime path.

## E2 Swarm coordination on current runtime

Status: pending

### Outcome

Add explicit multi-agent coordination as a first-class feature, but implemented as an orchestration layer over current components instead of a new agent platform.

### Design direction

- Build on `claims`, `workflow`, `agent-pool`, `/reservation`, `/bg`, and current subagent contracts.
- Use a swarm plan artifact that assigns roles, dependencies, reservation scopes, validation gates, and merge rules.
- Keep a single canonical coordinator command family rather than many topology-branded commands.
- Support controlled fan-out for read-only discovery/review and guarded fan-in for write phases.

### Canonical command decision

- Start E2 by proving the state model and execution flow on top of existing `workflow`, `claims`, `reservation`, and `agent-pool` contracts.
- Introduce `/swarm` only if that prototype shows the coordination behavior is too dense for `workflow` subcommands and needs a clearer operator surface.
- If `/swarm` is introduced, it becomes the single canonical family for multi-lane coordination; do not mirror the same behavior under `/workflow`.

### Proposed command surface

- Phase 1 prototype under existing commands: `workflow`, `claims`, `reservation`, `agent-pool`, and `bg`
- Phase 2 canonical surface if justified:
- `/swarm plan`
- `/swarm start`
- `/swarm status`
- `/swarm rebalance`
- `/swarm checkpoint`
- `/swarm handoff`
- `/swarm close`

### Detailed tasks

- [ ] E2-T1 Define swarm run schema: objective, lanes, owners, reservations, acceptance criteria, and stop reasons.
- [ ] E2-T2 Add coordinator state storage reusing workflow/claim identifiers where possible.
- [ ] E2-T3 Add lane types for discovery, implementation, review, verifier, and release-prep.
- [ ] E2-T4 Integrate reservation enforcement so overlapping writers are blocked or serialized automatically.
- [ ] E2-T5 Add progress aggregation from subagent outputs, validations, and unresolved blockers.
- [ ] E2-T6 Add rebalance rules for stuck lanes, failed validations, and repeated review findings.
- [ ] E2-T7 Add handbook/operator docs and examples for safe same-session fan-out.
- [ ] E2-T8 Add selftests for lane scheduling, blocked writes, resume, handoff, and failure recovery.

### Done criteria

- Operators can run coordinated multi-agent plans without leaving the current runtime.
- Write safety remains compatible with worktree-first rules and reservations.
- Swarm state is resumable, inspectable, and handoff-friendly.

## E3 Plugin platform expansion

Status: pending

### Outcome

Evolve `gateway-core` from a single maintained plugin into a stable plugin platform with explicit contracts for safe extensions, while keeping MCP out of scope.

### Design direction

- Keep `gateway-core` as the base runtime and add a plugin-pack model on top.
- Support three extension classes: hooks, command packs, and diagnostics packs.
- Require metadata for version, capabilities, risk level, required commands, and validation hooks.
- Prefer local file-based manifests and deterministic loading.

### Detailed tasks

- [ ] E3-T1 Define plugin-pack manifest schema and compatibility/version rules.
- [ ] E3-T2 Add plugin discovery, enable/disable state, and dependency/conflict checks.
- [ ] E3-T3 Add a stable hook API for event input, output, reason codes, and telemetry.
- [ ] E3-T4 Add command-pack registration so plugins can contribute canonical subcommands safely.
- [ ] E3-T5 Add diagnostics-pack support so plugins can extend `/doctor` and selftest registration.
- [ ] E3-T6 Add sandboxing rules, performance budgets, and failure isolation for plugin packs.
- [ ] E3-T7 Add author docs, example packs, and migration guidance from ad hoc runtime customization.
- [ ] E3-T8 Add validation for plugin conflicts, upgrade/downgrade safety, and broken-pack recovery.

### Done criteria

- A new capability can be shipped as a pack without patching core runtime files in most cases.
- Plugin failures degrade safely and are diagnosable through `/plugin doctor`.
- The platform stays narrower and safer than a generic marketplace.

## E4 Operations automation expansion

Status: pending

### Outcome

Expand automation for issue delivery, PR preparation, release management, hotfixes, and incident response using the current deterministic command philosophy.

### What to borrow and improve from `claude-flow`

- Borrow: richer GitHub/ops workflows, rollback-ready thinking, and automation around release/issue/PR handling.
- Improve locally: route all automation through `claims`, `delivery`, `workflow`, `review`, `release-train`, `hotfix`, `doctor`, and the `agents.md` completion gates.
- Avoid: broad automation that bypasses worktree safety, validation evidence, or reviewer/verifier passes.

### Proposed command areas

- strengthen `/delivery`
- strengthen `/review`
- strengthen `/release-train`
- strengthen `/hotfix`
- strengthen `/daemon`
- add focused GitHub automation only when it maps cleanly onto current canonical commands

### Detailed tasks

- [ ] E4-T1 Add issue-to-plan scaffolding that turns a claim into a validated workflow or plan artifact.
- [ ] E4-T2 Add PR preparation helpers that compile `why`, `risk`, `verify`, validation evidence, and reviewer checklist sections.
- [ ] E4-T3 Add release-train automation for milestone rollups, candidate validation, changelog drafting, and promotion checks.
- [ ] E4-T4 Add hotfix automation for rollback checkpoints, incident metadata capture, and follow-up issue creation.
- [ ] E4-T5 Add daemon-driven hygiene jobs for stale claims, stale worktrees, validation reminders, and branch freshness checks.
- [ ] E4-T6 Add structured escalation paths that automatically route repeated failures to `oracle`, `reviewer`, or manual handoff.
- [ ] E4-T7 Add ops dashboards/reports from existing local state instead of external services first.
- [ ] E4-T8 Add selftests and runbooks for issue, PR, release, and hotfix happy paths plus degraded modes.

### Done criteria

- Repetitive operations work becomes a guided deterministic flow rather than manual glue.
- Every automation path emits evidence suitable for handoff, PRs, and release review.
- Automation respects the existing worktree, validation, and completion-gate model.

## Execution order

1. Finish E1 schema and retrieval baseline.
2. Start E2 with the shared memory hooks needed for swarm checkpointing and lane recall.
3. Start E4 once E2 state contracts are stable enough to automate issue-to-plan and PR/release flows.
4. Start E3 after the swarm and ops contracts reveal the right stable extension points.

## Validation gates for every epic

- `make validate`
- `make selftest`
- `make install-test`
- `npm --prefix plugin/gateway-core run lint`
- `npm --prefix plugin/gateway-core run test`
- targeted scenario validation for the changed command/runtime path

## Worklog

| UTC | Item | Status | Notes |
| --- | --- | --- | --- |
| 2026-03-10T00:00:00Z | E13 plan opened | doing | Captured owner decisions after `claude-flow` comparison and mapped them onto the current `my_opencode` architecture; keep this row open until the planning slice is merged. |

## Next implementation slice

- doing: E1-T1 define shared-memory schema, ranking model, and retention policy.
- next: E1-T2 decide whether to extend the current memory store or create a new `shared-memory` namespace under the same local runtime root.
- next: E1-T3 map digest, handoff, workflow, and claim artifacts into deterministic memory promotion rules.
