# E13 Shared Memory, Swarm, Plugin, and Ops Automation Plan

Date: 2026-03-10
Owner: OpenCode orchestrator
Status: doing

## Scope locks

- shared memory stays local-first
- no external APIs
- no vector search
- extend current runtime instead of adding a second one
- plugin-platform work is in scope
- MCP expansion is out of scope

## Status legend

- pending
- doing
- done
- blocked

## Quick board

| Epic | Priority | State | Goal | Notes |
| --- | --- | --- | --- | --- |
| E1 Local shared memory runtime | P0 | doing | add durable local shared memory with deterministic retrieval | initial slice is schema + command/runtime baseline |
| E2 Swarm coordination on current runtime | P0 | doing | layer multi-agent coordination on `workflow`, `claims`, `reservation`, and `agent-pool` | prototype lives under `/workflow swarm` first |
| E3 Plugin platform expansion | P1 | pending | turn `gateway-core` into a safer plugin-pack platform | keep MCP out of scope |
| E4 Operations automation expansion | P0 | doing | improve issue, PR, release, and hotfix automation | route through existing canonical commands; first slice is readiness diagnostics across `/delivery`, `/ship`, `/release-train`, and `/hotfix` |

## E1 Local shared memory runtime

Status: doing

### Design choices

- use local SQLite storage for durability and lock-safe access
- use FTS/BM25 lexical retrieval instead of embeddings or vector search
- keep `/memory` for content operations and `/memory-lifecycle` for lifecycle/admin operations
- attach scope, namespace, tags, confidence, session id, and cwd metadata to each record

### Tasks

- [x] E1-T1 Define canonical shared-memory schema and ranking contract.
- [x] E1-T2 Add local durable storage with lock-safe access.
- [x] E1-T3 Implement initial lexical retrieval and recall flow.
- [x] E1-T4 Add promotion rules from digests, handoffs, workflow runs, claim history, and saved doctor findings.
- [ ] E1-T5 Add richer namespace/session/worktree scoping rules.
- [x] E1-T6 Add slash command surface, doctor integration, and handbook docs.
- [x] E1-T7 Converge lifecycle admin flows with the shared-memory runtime.
- [x] E1-T8 Add initial selftest coverage for add/find/recall/pin/doctor.

### Current slice delivered

- added `scripts/shared_memory_runtime.py`
- added `scripts/memory_command.py`
- added `/memory` command registration in `opencode.json`
- added `/doctor` integration for the new memory runtime
- added handbook and README visibility for the new command
- added selftest coverage for the baseline command flow
- added `/memory promote` for digest/session/workflow/claims promotion into shared memory
- converged `/memory-lifecycle` stats/export/import/cleanup/compress/doctor onto the SQLite-backed shared-memory runtime

### Next slice

- [x] Add richer memory links and surfaced relationships between promoted artifacts.
- add linking and richer summarize/query behavior once promotion inputs exist

## Worklog

| UTC | Item | Status | Notes |
| --- | --- | --- | --- |
| 2026-03-11T08:00:00Z | E13 implementation branch opened | done | Started dedicated worktree branch `feat/shared-memory-runtime`; branch evidence: https://github.com/dmoliveira/my_opencode/compare/main...feat/shared-memory-runtime |
| 2026-03-11T08:05:00Z | E1 shared-memory baseline | done | Added local SQLite runtime, `/memory` command, doctor wiring, docs, and selftests; branch evidence: https://github.com/dmoliveira/my_opencode/compare/main...feat/shared-memory-runtime |
| 2026-03-10T13:05:00Z | E1 promotion pipeline | doing | Added `/memory promote` for digest/session/workflow/claims artifact promotion plus selftest coverage. |
| 2026-03-10T13:20:00Z | E1 doctor promotion hardening | doing | Added doctor-report promotion, idempotent source upserts, safer ID allocation, and FTS fallback behavior. |
| 2026-03-10T13:35:00Z | E1 lifecycle convergence | doing | Switched `/memory-lifecycle` admin flows to the shared-memory SQLite runtime and added export/import roundtrip coverage. |
| 2026-03-10T13:50:00Z | E1 relationship linking | doing | Added derived `memory-ref:` links across related promoted memories and covered the behavior in selftest. |
| 2026-03-10T14:10:00Z | E2 swarm prototype | doing | Added `/workflow swarm` plan/status/doctor/close on top of workflow, claims, agent-pool, and reservation state with selftest coverage. |
| 2026-03-10T14:25:00Z | E2 swarm handoff/rebalance | doing | Added `/workflow swarm handoff` and `/workflow swarm rebalance` with lane mutation and health coverage in selftest. |
| 2026-03-10T14:40:00Z | E2 swarm execution bridge | doing | Added `/workflow swarm accept-handoff` plus controlled background-job enqueueing for allowed commands. |
| 2026-03-10T15:00:00Z | E2 lane outcomes and progression | doing | Added `complete-lane`/`fail-lane` transitions plus swarm-level progress summaries driven by lane outcomes. |
| 2026-03-10T15:20:00Z | E2 follow-up orchestration | doing | Added follow-up guidance and deterministic next-lane auto-progression after lane outcomes when the swarm is otherwise idle. |
| 2026-03-10T15:35:00Z | E2 failure recovery and coordination | doing | Added explicit failure-recovery policy output and conservative single-active-lane coordination rules. |
| 2026-03-10T15:50:00Z | E2 executable recovery and surfaced parallel capacity | doing | Added `reset-lane`/`retry-lane` recovery actions and surfaced conservative read-only parallel capacity without bypassing lane ordering. |
| 2026-03-10T16:05:00Z | E2 automated recovery decisions | doing | Added recommended recovery decisions plus `resolve-failure` execution on top of reset/retry flows. |
| 2026-03-10T16:20:00Z | E2 dependency metadata | doing | Added explicit `depends_on` lane metadata, dependency-aware activation/failure blocking logic, and surfaced dependency-qualified parallel candidates. |
| 2026-03-10T16:35:00Z | E2 custom lane graphs | doing | Added `--graph-file` support with custom swarm lane graph validation and runtime materialization. |
| 2026-03-10T16:50:00Z | E2 reservation-safe reads | doing | Added explicit reservation-safe read lane metadata and enabled dependency-satisfied parallel activation for read-only lanes when reservation guarantees are present. |
| 2026-03-10T17:05:00Z | E2 path-scope contracts | doing | Added explicit lane `path_scopes` plus overlap-aware coordination checks to prepare future safe write-capable parallelism. |
| 2026-03-10T17:20:00Z | E2 writer lease diagnostics | doing | Added lease-backed writer guarantee checks and surfaced disjoint write parallel candidates without enabling writer parallel execution. |
| 2026-03-10T17:35:00Z | E2 tiny writer allowlist | doing | Enabled lease-backed parallel activation for disjoint `implement` lanes while keeping all other writer lanes serialized. |
| 2026-03-10T17:50:00Z | E2 lane lease identity | doing | Added lane-level `lease_identity` metadata and enforced it for write-capable activation paths. |
| 2026-03-13T21:10:00Z | E4 ops automation diagnostics slice | doing | Added `/ship doctor` and umbrella `/doctor` coverage so issue, PR, release, and hotfix automation can be audited from canonical commands before deeper workflow automation lands. |
| 2026-03-13T21:20:00Z | E4 delivery-to-ship handoff summary | doing | Added canonical `/delivery` runtime summary pickup in `/ship doctor` plus `/ship create-pr --issue <id>` template enrichment for matched delivery runs. |
| 2026-03-13T21:28:00Z | E4 hotfix follow-up audit | doing | Added latest-closure follow-up linkage auditing in `/hotfix doctor` so umbrella `/doctor` can surface incident follow-up drift through canonical command wiring. |
| 2026-03-13T21:31:00Z | E4 delivery doctor status audit | doing | Added latest-run delivery summaries plus handoff-pending/workflow-failed warnings in `/delivery doctor` so issue-flow drift surfaces through canonical diagnostics. |
