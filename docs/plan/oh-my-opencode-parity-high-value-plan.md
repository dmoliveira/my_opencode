# Oh-My-OpenCode High-Value Parity Plan

Date: 2026-02-19
Owner: `br` task `bd-1n9`
Scope: close high-value parity gaps while reusing existing `my_opencode` systems and avoiding duplicate runtimes.

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
| E6 Packaged CLI parity (`install/doctor/run`) | P2 | 󰄱 [ ] backlog | Not started | CLI contract | Waiting on E1 | - |

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
- [ ] E6 Packaged CLI parity
  - [ ] E6-T1 Define packaged CLI contract (`install`, `doctor`, `run`, `version`).
  - [ ] E6-T2 Implement packaged entrypoint and non-interactive argument parsing.
  - [ ] E6-T3 Normalize diagnostics/failure reasons.
  - [ ] E6-T4 Add install/selftest coverage in clean HOME.
  - [ ] E6-T5 Add docs and CI-safe examples.

Progress counters:
- Epics completed: `6/7`
- Tasks completed: `30/35`

## Parity coverage map

| Upstream high-value capability | Plan coverage | Status |
| --- | --- | --- |
| Persistent dependency task tools | E1 | finished |
| Loop-oriented slash workflows | E2 | finished |
| Built-in skill trio | E3 | finished |
| Planning-specialist roles | E4 | finished |
| Tmux visual multi-agent mode | E5 | finished |
| Packaged top-level CLI (`install/doctor/run`) | E6 | planned |
| Local command/hook drift prevention (value-add) | E0 | finished |

Note: MCP OAuth parity is intentionally out-of-scope for this cycle.

## Naming and accessibility policy (plain-English, low cognitive load)

Goal: keep command and role names obvious, short, and aligned with what already exists.

Rules:
- Prefer existing command families (`/autopilot`, `/autoflow`, current agent roles) over introducing new names.
- Add new slash commands only when a capability gap cannot be solved by improving existing commands.
- If parity requires compatibility aliases, keep them minimal and document one canonical command.
- Avoid branding-oriented names that increase cognitive load without adding functional clarity.

Canonical command strategy for E2:

| Intent | Canonical command | Compatibility policy |
| --- | --- | --- |
| Deep execution initialization | existing `/autopilot` + objective/profile inputs | add alias only if parity requires |
| Continuous autonomous loop | existing `/autopilot` runtime controls | add alias only if migration risk is high |
| Build/craft loop workflow | existing `/autoflow` and related runtime commands | avoid new command unless gap is proven |

Optional compatibility note:
- If `/autoloop` is requested for familiarity, implement it as a thin alias to existing `/autopilot` behavior (no separate runtime).

Canonical role strategy for E4:

| Role label in UI/docs | Purpose |
| --- | --- |
| `Strategic Planner` | plan synthesis and sequencing |
| `Ambiguity Analyst` | hidden assumptions and risk discovery |
| `Plan Critic` | quality review before execution |

## Reuse-first guardrails (no duplication)

- E1 must build on existing `/autoflow`, `/todo`, `/resume`, and `/checkpoint` state patterns.
- E2 must improve/reuse existing loop behavior over autopilot + keyword + continuation logic.
- E3 must route through existing browser/git/frontend constraints and tools.
- E4 must use existing role/spec framework and `agent-doctor`.
- E5 must reuse current pane/session and background orchestration utilities.
- E6 must call existing backend scripts; slash commands remain first-class.

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
| 2026-02-19T01:44:00Z | E0-T1..E0-T5 | Added hygiene rubric, alias/hook audit, naming simplification, and migration guidance | `docs/plan/e0-command-hook-hygiene-audit.md`, `opencode.json` |
| 2026-02-19T01:46:00Z | E0-T6 | Added automated drift checks and wired into validation target | `scripts/hygiene_drift_check.py`, `Makefile` |
