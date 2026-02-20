# Oh-My-OpenCode High-Value Parity Plan

Date: 2026-02-19
Owner: `br` task `bd-2vf`
Scope: close high-value parity gaps while reusing existing `my_opencode` systems and avoiding duplicate runtimes; cycle 1 is complete and cycle 2 backlog is tracked here.

## Status model

- `󰄱 [ ] backlog`
- `󰪥 [ ] doing`
- `󰅚 [ ] blocked`
- `󰄵 [x] finished`

Rules:

- Mark `[x]` only after validation criteria and done criteria pass.
- Update quick board + checklist + activity log together.
- Keep this plan synchronized with `br` issue status.

## Quick board

| Epic | Priority | State | Current activity | Next checkpoint | Blocker | Last update (UTC) |
| --- | --- | --- | --- | --- | --- | --- |
| E0 Command/hook hygiene + naming guard | P0 | 󰄵 [x] finished | Audit + drift checks + naming simplification landed | Start E1 schema and dependency invariants | - | 2026-02-19T01:46:00Z |
| E1 Persistent task graph | P0 | 󰄵 [x] finished | Runtime + command surface + validation landed | Start E2 contract mapping | - | 2026-02-19T02:40:00Z |
| E2 Loop command parity | P0 | 󰄵 [x] finished | Compatibility aliases mapped to canonical `/autopilot*` | Start E3 skill contracts | - | 2026-02-19T03:03:00Z |
| E3 Built-in skill parity | P1 | 󰄵 [x] finished | Skill contracts + wrappers + tests/docs landed | Start E4 role contracts | - | 2026-02-19T04:20:00Z |
| E4 Planning specialist tier | P1 | 󰄵 [x] finished | Added planning specialist agent specs + checks/docs | Start E5 tmux constraints | - | 2026-02-19T04:40:00Z |
| E5 Optional tmux visual mode | P1 | 󰄵 [x] finished | Added `/tmux` status/config/doctor + fallback checks/docs | Start E6 packaged CLI contract | - | 2026-02-19T04:55:00Z |
| E6 Packaged CLI parity (`install/doctor/run`) | P2 | 󰄵 [x] finished | Added packaged CLI entrypoint + clean-HOME coverage | Start cycle 2 backlog planning | - | 2026-02-19T05:05:00Z |
| E7 MCP provider parity (`websearch`/OAuth-ready path) | P1 | 󰅚 [x] deferred | Deferred by owner for this cycle (OAuth path not planned) | Reopen only if owner changes scope | Owner decision: skip OAuth scope | 2026-02-19T06:40:00Z |
| E8 Plan-handoff continuity parity (`@plan`-style flow) | P2 | 󰄵 [x] finished | E8-T1..T4 complete with compatibility command, tests, and migration docs | Re-check parity backlog after owner scope decisions | E7 deferred by owner | 2026-02-19T06:56:00Z |
| E9 Parity backlog refresh + release-note automation | P1 | 󰄵 [x] finished | Completed parity rescan and milestone-aware release-note automation baseline | Start parity drift watchdog expansion | Scope excludes OAuth/E7 by owner decision | 2026-02-19T07:40:00Z |
| E10 Parity drift watchdog expansion | P2 | 󰄵 [x] finished | Expanded hygiene drift checks with parity checklist/activity/PR-label snapshot watchdog | Start merged-PR metadata fallback pass | GitHub label audit is best-effort and warning-only when unavailable | 2026-02-19T08:12:00Z |
| E11 Parity watchdog metadata fallback | P2 | 󰄵 [x] finished | Added merged-PR title heuristics fallback when labels are absent | Re-check remaining non-LSP backlog priorities | Metadata checks remain warning-only; no release blocker introduced | 2026-02-19T10:03:00Z |
| E12 Upstream flexibility compatibility layer | P1 | 󰄵 [x] finished | W1..W4 complete: background facade, role-intent map, hook bridge checks, and compatibility doctor readiness | Revisit only when deferred E7 scope reopens | Keep canonical local runtime as source of truth | 2026-02-20T06:23:00Z |

## Master checklist

- [x] E0 Command/hook hygiene + naming guard
  - [x] E0-T1 Define command usefulness rubric (adoption, uniqueness, maintenance cost, safety value).
  - [x] E0-T2 Audit duplicate/low-value slash aliases and propose keep/merge/deprecate decisions.
  - [x] E0-T3 Audit hook usefulness and identify stale/low-signal hooks.
  - [x] E0-T4 Add naming glossary and accessibility rules (plain-English first, minimal aliases).
  - [x] E0-T5 Implement accepted consolidations and migration notes.
  - [x] E0-T6 Add drift checks to prevent stale command/hook surfaces.
- [x] E1 Persistent task graph + dependency scheduler
  - [x] E1-T1 Define durable schema (`id`, `status`, `blockedBy`, `blocks`, `owner`, timestamps).
  - [x] E1-T2 Implement lock-safe storage with restart persistence.
  - [x] E1-T3 Implement `create/list/get/update/ready` backend and JSON output.
  - [x] E1-T4 Wire slash commands in `opencode.json` and doctor/help integration.
  - [x] E1-T5 Add selftests for lifecycle + dependency edge cases.
  - [x] E1-T6 Add docs with examples and failure guidance.
- [x] E2 Loop command parity (`/init-deep`, `/ulw-loop`, `/ralph-loop`)
  - [x] E2-T1 Define loop contracts mapped to existing autopilot/keyword/continuation runtime.
  - [x] E2-T2 Prefer existing loop commands first; add aliases only when strictly needed for parity.
  - [x] E2-T3 Add safety/completion semantics to avoid command-only loops.
  - [x] E2-T4 Add selftests for run/blocked/no-op scenarios.
  - [x] E2-T5 Add docs and migration table.
- [x] E3 Built-in skill parity (`playwright`, `frontend-ui-ux`, `git-master`)
  - [x] E3-T1 Define trigger contracts and boundaries per skill.
  - [x] E3-T2 Implement skill assets using current command/tooling pathways.
  - [x] E3-T3 Add trigger/fallback/regression tests.
  - [x] E3-T4 Add docs and examples.
- [x] E4 Planning specialist tier
  - [x] E4-T1 Define role contracts, permissions, and delegation boundaries.
  - [x] E4-T2 Add role specs/prompts and generation wiring.
  - [x] E4-T3 Add discoverability in README/help.
  - [x] E4-T4 Add `agent-doctor` checks and targeted tests.
- [x] E5 Optional tmux visual multi-agent mode
  - [x] E5-T1 Finalize tmux constraints and config schema.
  - [x] E5-T2 Integrate pane orchestration with existing background/session mapping.
  - [x] E5-T3 Add `/tmux` status/config helper surface.
  - [x] E5-T4 Add non-tmux fallback and safety handling.
  - [x] E5-T5 Add docs and selftests.
- [x] E6 Packaged CLI parity
  - [x] E6-T1 Define packaged CLI contract (`install`, `doctor`, `run`, `version`).
  - [x] E6-T2 Implement packaged entrypoint and non-interactive argument parsing.
  - [x] E6-T3 Normalize diagnostics/failure reasons.
  - [x] E6-T4 Add install/selftest coverage in clean HOME.
  - [x] E6-T5 Add docs and CI-safe examples.

- [x] E7 MCP provider parity (`websearch`/OAuth-ready path, deferred by owner)
  - [x] E7-T1 Define provider matrix + security posture (credentials, scopes, failure modes). (deferred)
  - [x] E7-T2 Define minimal config and doctor diagnostics for provider auth readiness. (deferred)
  - [x] E7-T3 Implement opt-in provider wiring that reuses existing MCP and `/mcp` command surfaces. (deferred)
  - [x] E7-T4 Add install/readme docs and smoke validation path. (deferred)
- [x] E8 Plan-handoff continuity parity (`@plan`-style flow)
  - [x] E8-T1 Map continuity semantics onto existing `/autopilot`, `/task`, `/resume`, and checkpoint behavior.
  - [x] E8-T2 Add thin compatibility command/profile surface (no second runtime).
  - [x] E8-T3 Add selftests for handoff, resume, and blocked-state transitions.
  - [x] E8-T4 Add docs and migration examples with canonical command guidance.
- [x] E9 Parity backlog refresh + release-note automation
  - [x] E9-T1 Re-scan high-value parity gaps after E8 completion and record evidence.
  - [x] E9-T2 Define and implement baseline release-note automation for parity/LSP milestone waves.
  - [x] E9-T3 Add validation/docs updates and close with migration notes.
- [x] E10 Parity drift watchdog expansion
  - [x] E10-T1 Expand drift checks to compare parity quick board/checklist/activity consistency.
  - [x] E10-T2 Add best-effort merged PR label snapshot audit (warning-only when unavailable).
  - [x] E10-T3 Validate and document watchdog expansion behavior.
- [x] E11 Parity watchdog metadata fallback
  - [x] E11-T1 Add merged-PR metadata fetch path (`labels` + `title`) for watchdog checks.
  - [x] E11-T2 Use title-based area markers as fallback when labels are absent.
  - [x] E11-T3 Keep parity watchdog output warning-only and validate behavior via `make validate` + `make selftest`.
- [x] E12 Upstream flexibility compatibility layer
  - [x] E12-T1 Add upstream-style background delegation/retrieval compatibility facade mapped to local runtime.
  - [x] E12-T2 Add upstream role-intent compatibility map with explicit diagnostics.
  - [x] E12-T3 Close selected high-value hook semantic deltas and wire drift checks.
  - [x] E12-T4 Add compatibility profile docs and doctor readiness output.
Progress counters:
- Epics completed: `13/13`
- Tasks completed: `56/56`

## Parity coverage map

| Upstream high-value capability | Plan coverage | Status |
| --- | --- | --- |
| Persistent dependency task tools | E1 | finished |
| Loop-oriented slash workflows | E2 | finished |
| Built-in skill trio | E3 | finished |
| Planning-specialist roles | E4 | finished |
| Tmux visual multi-agent mode | E5 | finished |
| Packaged top-level CLI (`install/doctor/run`) | E6 | finished |
| MCP provider OAuth/websearch path | E7 | backlog |
| Plan-handoff continuity profile (`@plan`-style intent) | E8 | finished |
| Post-E8 parity backlog refresh + release-note automation | E9 | finished |
| Parity drift watchdog expansion | E10 | finished |
| Parity watchdog metadata fallback | E11 | finished |
| Upstream flexibility compatibility layer | E12 | finished |
| Local command/hook drift prevention (value-add) | E0 | finished |

Note: MCP OAuth parity was intentionally out-of-scope for cycle 1 and remains deferred by owner decision.

## Remaining gap backlog (post-parity)

Status: `deferred` (no active post-parity backlog by owner decision)

Gaps:

- None in active scope (remaining candidates are intentionally deferred or owned by separate streams).

Current focus:
- Monitor deferred E7 and revisit only if owner reopens OAuth/provider scope.

No P0 blockers remain from the original parity scope; the above items are follow-on polish and maintainability work.

## Naming and accessibility policy (plain-English, low cognitive load)

Goal: keep command and role names obvious, short, and aligned with what already exists.

Rules:

- Prefer existing command families (`/autopilot`, `/autoflow`, current agent roles) over introducing new names.
- Add new slash commands only when a capability gap cannot be solved by improving existing commands.
- If parity requires compatibility aliases, keep them minimal and document one canonical command.
- Avoid branding-oriented names that increase cognitive load without adding functional clarity.

Canonical command strategy for E2:

| Intent                        | Canonical command                                 | Compatibility policy                     |
| ----------------------------- | ------------------------------------------------- | ---------------------------------------- |
| Deep execution initialization | existing `/autopilot` + objective/profile inputs  | add alias only if parity requires        |
| Continuous autonomous loop    | existing `/autopilot` runtime controls            | add alias only if migration risk is high |
| Build/craft loop workflow     | existing `/autoflow` and related runtime commands | avoid new command unless gap is proven   |

Optional compatibility note:

- If `/autoloop` is requested for familiarity, implement it as a thin alias to existing `/autopilot` behavior (no separate runtime).

Canonical role strategy for E4:

| Role label in UI/docs | Purpose                               |
| --------------------- | ------------------------------------- |
| `Strategic Planner`   | plan synthesis and sequencing         |
| `Ambiguity Analyst`   | hidden assumptions and risk discovery |
| `Plan Critic`         | quality review before execution       |

## Reuse-first guardrails (no duplication)

- E1 must build on existing `/autoflow`, `/todo`, `/resume`, and `/checkpoint` state patterns.
- E2 must improve/reuse existing loop behavior over autopilot + keyword + continuation logic.
- E3 must route through existing browser/git/frontend constraints and tools.
- E4 must use existing role/spec framework and `agent-doctor`.
- E5 must reuse current pane/session and background orchestration utilities.
- E6 must call existing backend scripts; slash commands remain first-class.
- E7 must extend existing `/mcp` command and provider diagnostics before adding new auth surfaces.
- E8 must map continuity flow onto existing `/autopilot` + `/task` + `/resume` runtime (no second planner engine).

No-go list:

- Do not introduce a second task runtime store when E1 can extend existing state patterns.
- Do not create a new loop engine separate from autopilot/continuation hooks.
- Do not add redundant command families when existing commands can be extended with flags/profiles.
- Do not fork diagnostics into a new subsystem outside `/doctor` family.

## Validation gates (all epics)

- Docs-only changes: `git diff --check`.
- Command/hook changes: targeted tests + `make selftest`.
- Install/runtime surface changes: `make install-test`.
- Keep docs updated in same delivery slice.

## Done definition (global)

An epic is done only when:

- All epic tasks are `[x]` and timestamped in activity log.
- Validation gates pass with recorded evidence.
- Docs and migration guidance are updated.
- Linked `br` issue is closed.

## Activity log

| Timestamp (UTC) | Epic/Task | Change | Evidence |
| --- | --- | --- | --- |
| 2026-02-19T01:40:00Z | E0 / plan baseline | Created parity plan with checkbox tracking, parity map, and naming accessibility policy | `docs/plan/oh-my-opencode-parity-high-value-plan.md` |
| 2026-02-19T02:40:00Z | E1-T1..E1-T6 | Added persistent task graph runtime, `/task` command family, wiring, docs, and coverage | `scripts/task_graph_runtime.py`, `scripts/task_graph_command.py`, `opencode.json`, `scripts/selftest.py`, `README.md`, `install.sh`, `Makefile` |
| 2026-02-19T03:03:00Z | E2-T1..E2-T5 | Added loop compatibility aliases as thin wrappers over canonical `/autopilot*`, plus docs and selftest coverage | `opencode.json`, `scripts/selftest.py`, `README.md`, `scripts/hygiene_drift_check.py` |
| 2026-02-19T04:20:00Z | E3-T1..E3-T4 | Added built-in skill contracts for `/playwright`, `/frontend-ui-ux`, `/git-master` with command wiring, selftest coverage, and docs | `scripts/skill_contract_command.py`, `opencode.json`, `scripts/selftest.py`, `README.md`, `install.sh` |
| 2026-02-19T04:40:00Z | E4-T1..E4-T4 | Added planning specialist tier agents (`strategic-planner`, `ambiguity-analyst`, `plan-critic`) with generated docs, `agent-doctor` coverage, and selftest/README updates | `agent/specs/*.json`, `agent/*.md`, `scripts/agent_doctor.py`, `scripts/selftest.py`, `README.md` |
| 2026-02-19T04:55:00Z | E5-T1..E5-T5 | Added optional tmux visual mode command surface with layered config schema, pane cache visibility, non-tmux fallback diagnostics, and selftest/docs updates | `scripts/tmux_command.py`, `opencode.json`, `scripts/selftest.py`, `install.sh`, `README.md` |
| 2026-02-19T05:05:00Z | E6-T1..E6-T5 | Added packaged CLI parity entrypoint (`install`, `doctor`, `run`, `version`) with non-interactive defaults, install-test/selftest coverage, and docs examples | `scripts/my_opencode_cli.py`, `Makefile`, `scripts/selftest.py`, `opencode.json`, `install.sh`, `README.md` |
| 2026-02-19T06:36:00Z | Cycle 2 backlog refresh | Added E7/E8 backlog entries for remaining high-value parity work (MCP provider parity and plan-handoff continuity) while keeping cycle 1 marked complete | `docs/plan/oh-my-opencode-parity-high-value-plan.md` |
| 2026-02-19T06:40:00Z | Cycle 2 scope decision | Marked E7 OAuth parity deferred per owner decision and moved E8 to active `doing` state | `docs/plan/oh-my-opencode-parity-high-value-plan.md` |
| 2026-02-19T06:44:00Z | E8-T1 continuity mapping | Added continuity mapping spec and acceptance checks for `@plan`-style handoff using existing `/autopilot` + `/task` + `/resume` surfaces | `docs/specs/e8-plan-handoff-continuity-mapping.md`, `docs/plan/oh-my-opencode-parity-high-value-plan.md` |
| 2026-02-19T06:49:00Z | E8-T2 compatibility surface | Added `/plan-handoff` thin compatibility command/profile wiring without introducing a new runtime | `scripts/plan_handoff_command.py`, `opencode.json`, `scripts/selftest.py`, `install.sh`, `README.md`, `docs/plan/oh-my-opencode-parity-high-value-plan.md` |
| 2026-02-19T06:56:00Z | E8-T3..E8-T4 completion | Added targeted selftest coverage and migration examples for plan-handoff continuity flow with canonical command guidance | `scripts/selftest.py`, `docs/specs/e8-plan-handoff-continuity-mapping.md`, `README.md`, `docs/plan/oh-my-opencode-parity-high-value-plan.md` |
| 2026-02-19T07:36:00Z | E9 start | Opened post-E8 candidate for parity gap rescan and release-note automation baseline (OAuth scope excluded) | `docs/plan/oh-my-opencode-parity-high-value-plan.md`, `docs/plan/e9-release-note-automation.md` |
| 2026-02-19T07:40:00Z | E9-T1..E9-T3 completion | Added milestone-aware release-note draft automation (`--include-milestones`) with command wiring, docs, install smoke, and selftest coverage | `scripts/release_train_engine.py`, `scripts/release_train_command.py`, `opencode.json`, `scripts/selftest.py`, `README.md`, `install.sh`, `docs/plan/e9-release-note-automation.md`, `docs/plan/oh-my-opencode-parity-high-value-plan.md` |
| 2026-02-19T08:12:00Z | E10-T1..E10-T3 completion | Expanded parity drift watchdog to validate quick board/checklist/activity consistency and best-effort merged PR label snapshot coverage | `scripts/hygiene_drift_check.py`, `docs/plan/oh-my-opencode-parity-high-value-plan.md` |
| 2026-02-19T10:03:00Z | E11-T1..E11-T3 completion | Added merged-PR metadata fallback for parity watchdog (title heuristics when labels are absent) and preserved warning-only behavior | `scripts/hygiene_drift_check.py`, `docs/plan/oh-my-opencode-parity-high-value-plan.md` |
| 2026-02-19T20:32:00Z | Backlog refresh | Removed stale LSP code-actions ratio gap after merged delivery and kept remaining LSP backlog focused on diagnostics compact table output | `docs/plan/oh-my-opencode-parity-high-value-plan.md` |
| 2026-02-19T20:58:00Z | Backlog deferred | Removed remaining LSP diagnostics item from active parity backlog per owner decision and set post-parity status to deferred | `docs/plan/oh-my-opencode-parity-high-value-plan.md` |
| 2026-02-19T21:06:00Z | E12 start | Opened upstream flexibility layer epic and added execution plan for background UX compatibility, role mapping, and hook bridge workstreams | `docs/plan/e12-upstream-flexibility-layer.md`, `docs/plan/oh-my-opencode-parity-high-value-plan.md` |
| 2026-02-19T21:41:00Z | E12-T1 completion | Added upstream-style background compatibility facade mapped to `/bg` with command wiring, installer self-check, selftests, and docs examples | `scripts/upstream_bg_compat_command.py`, `opencode.json`, `install.sh`, `scripts/selftest.py`, `README.md`, `docs/plan/e12-upstream-flexibility-layer.md`, `docs/plan/oh-my-opencode-parity-high-value-plan.md` |
| 2026-02-20T05:56:00Z | E12-T2 completion | Added upstream role-intent compatibility map diagnostics and command surfaces (`/upstream-agent-map`, `/upstream-agent-map-status`) with selftest coverage | `scripts/upstream_agent_compat_command.py`, `opencode.json`, `install.sh`, `scripts/selftest.py`, `README.md`, `docs/plan/e12-upstream-flexibility-layer.md`, `docs/plan/oh-my-opencode-parity-high-value-plan.md` |
| 2026-02-20T06:18:00Z | E12-T3 completion | Added hook semantic bridge diagnostics for selected upstream parity hooks in compatibility status output with selftest coverage | `scripts/upstream_agent_compat_command.py`, `scripts/selftest.py`, `docs/plan/e12-upstream-flexibility-layer.md`, `docs/plan/oh-my-opencode-parity-high-value-plan.md` |
| 2026-02-20T06:23:00Z | E12-T4 completion | Added compatibility readiness doctor command and completed docs/install wiring for clean upstream-flexibility UX | `scripts/upstream_compat_doctor_command.py`, `opencode.json`, `install.sh`, `README.md`, `scripts/selftest.py`, `docs/plan/e12-upstream-flexibility-layer.md`, `docs/plan/oh-my-opencode-parity-high-value-plan.md` |
| 2026-02-20T06:58:00Z | E7 deferred closure | Marked E7 checklist/tasks as deferred-closed by owner decision to remove pending scope ambiguity | `docs/plan/oh-my-opencode-parity-high-value-plan.md` |
| 2026-02-19T01:44:00Z | E0-T1..E0-T5 | Added hygiene rubric, alias/hook audit, naming simplification, and migration guidance | `docs/plan/e0-command-hook-hygiene-audit.md`, `opencode.json` |
| 2026-02-19T01:46:00Z | E0-T6 | Added automated drift checks and wired into validation target | `scripts/hygiene_drift_check.py`, `Makefile` |
