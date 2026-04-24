# Agents Playbook 🧠

This guide explains how the custom agents in this repo work, when to use each one, and how they fit into real OpenCode workflows.

Goal: keep execution fast, safe, and low-friction while preserving the current default (`build`). ⚡

---

## Quick summary table 📋

| Agent | Type | Main job | Can edit code? | Best moment to use |
|---|---|---|---|---|
| `build` | primary (default) | Direct implementation | Yes | Small/clear tasks, quick fixes |
| `orchestrator` | primary | Lead complex multi-step delivery + delegate specialists | Yes | Medium/large tasks, end-to-end execution |
| `tasker` | primary | Planning-focused Codememory artifact capture | Contract-only | Backlog shaping, dependencies, durable notes |
| `explore` | subagent | Internal codebase discovery and pattern finding | No | "Where is X?" / multi-module discovery |
| `librarian` | subagent | External docs and OSS evidence lookup | No | Framework/library behavior, upstream examples |
| `oracle` | subagent | High-signal architecture/debug review | No | Hard tradeoffs, repeated failed attempts |
| `verifier` | subagent | Run/interpret tests, lint, build | No | After meaningful code changes |
| `reviewer` | subagent | Risk/correctness/maintainability review | No | Before declaring done |
| `release-scribe` | subagent | PR/changelog/release notes drafting | No | Final communication and release prep |
| `experience-designer` | subagent | Browser-first UX/UI audit and polish guidance | No | UX refinement, responsive review, accessibility polish |

---

## Agent model for this repo 🧭

- `build` remains the default for speed and familiarity.
- `orchestrator` is the execution lead for bigger flows.
- `tasker` is the planning-focused primary for Codememory-backed task, epic, dependency, and note capture.
- Specialist subagents are intentionally read-only to reduce accidental drift.
- `experience-designer` covers browser-first UX quality, while `reviewer` stays the final code/risk gate.
- Completion should only happen after implementation + validation + review gates pass.
- Model allocation defaults and fallbacks are documented in `docs/model-allocation-policy.md`.
- Browser automation should be treated as a narrow bridge for UI-owned blockers such as OAuth consent, install or re-auth prompts, scope upgrades, and final visual verification; return to shell/API tooling as soon as the blocker is cleared.

Architecture and safety contracts:

- `docs/agent-architecture.md`
- `docs/agent-tool-restrictions.md`

Think of it as:

`tasker` -> captures planning graph in Codememory

`orchestrator` -> delegates research/review tasks -> executes changes -> validates -> reports

---

## How to select agents (Tab menu) ⌨️

In OpenCode prompt:

1. Press `Tab`
2. Pick agent (`build`, `plan`, `orchestrator`, or `tasker`)
3. Run your prompt normally

Our custom specialist subagents are intentionally marked hidden, so they stay out of the `Tab` switcher and are used through delegation or explicit `@agent` mention instead.

You can verify available agents with:

```bash
opencode agent list
```

Validate agent contract + runtime wiring with:

This now also verifies orchestration policy markers in the nearest `AGENTS.md` (quickplay + WT checklist + pressure defaults).

```text
/agent-doctor
/agent-doctor --json
```

Runtime discoverability commands:

```text
/agent-catalog list
/agent-catalog explain orchestrator
/agent-catalog explain tasker
/agent-catalog doctor --json
```

When these hints appear automatically in execution flow:
- delegation router injects `/agent-catalog explain <subagent>` when it infers or applies routing metadata
- fallback orchestrator injects `/agent-catalog list` + explain hint when it rewrites a failed delegation path
- planning-only prompts that ask to capture backlog items, Codememory tasks, dependencies, epics, or durable notes can now route to `tasker` through the same delegation surface as the other specialists

---

## Real usage examples 🛠️

### 1) Small bug fix (stay on `build`)

Use when issue is isolated and file location is clear.

Example prompt:

```text
Fix the null-check bug in auth token parsing and run relevant tests.
```

Why: minimal overhead, direct implementation is fastest.

---

### 2) Multi-file feature (switch to `orchestrator`)

Use when request spans multiple modules and requires verification/review.

Example prompt:

```text
Implement end-to-end support for workspace profile presets, including docs and tests.
Keep iterating until done or a concrete blocker.
```

Expected flow:
- `orchestrator` may ask `explore` to map impacted files
- implements changes
- uses `verifier` for checks
- uses `reviewer` before final done claim

---

### 2b) Planning-only backlog capture (switch to `tasker`)

Use when you want to turn user intent into Codememory tasks, epics, dependencies, and durable notes without editing code.

Example prompt:

```text
Create an epic for workspace presets, add follow-on tasks for migration and docs, mark docs as depending on the migration task, and keep this as planning-only work.
```

Expected flow:
- `tasker` reads just enough repo context to name artifacts well
- checks Codememory for related items first
- writes tasks/epics/memories/links through `oc`
- returns created ids plus the inferred dependency graph
- `tasker` can be selected directly or delegated to when the prompt clearly asks for planning-only capture instead of implementation
- `python3 scripts/selftest.py` validates the `tasker` contract metadata plus the isolated Codememory artifact/link flow this planning path relies on
- `python3 scripts/tasker_e2e_sandbox.py --runs 30 --json` drives live `opencode run --agent tasker` simulations against sandboxed Codememory scopes when you want runtime-level confidence beyond selftest
- that live harness now mixes happy-path planning, duplicate-control, and planning-only execution-boundary scenarios so regressions surface under broader runtime pressure

---

### 3) External library behavior confusion (use `librarian`)

Example prompt:

```text
Find official docs and upstream examples for OpenCode agent file format and summarize best practice for read-only subagents.
```

Expected output:
- sources with links
- concise recommendation
- tradeoffs/notes

---

### 4) Architecture decision under uncertainty (use `oracle`)

Example prompt:

```text
Review this plan: replace default build flow with orchestrator globally.
Assess risks, migration strategy, and rollback plan.
```

Expected output:
- one recommended path
- key risks
- concrete next steps + effort sizing

---

### 5) Pre-merge validation gate (use `verifier` + `reviewer`)

Example prompt:

```text
Validate this branch and give me a ship/no-ship recommendation.
Run the fastest high-signal checks first, then broaden if needed.
```

Expected output:
- exact commands + results
- issue list by severity
- single best next action

---

### 6) PR and release communication (use `release-scribe`)

Example prompt:

```text
Draft PR summary + changelog bullets from this branch diff.
Include testing notes and user-facing impact.
```

Expected output:
- concise PR summary
- Adds/Changes/Fixes/Removals bullets
- release-note style blurb

---

## When to use `build` vs `orchestrator` ⚖️

If the request is planning-only, use `tasker` instead of either execution-focused primary.

Use `build` when:
- scope is clear
- <= 2 files touched
- no external research needed

Use `orchestrator` when:
- cross-module task
- unknown code ownership/locations
- non-trivial validation/review needed
- you want "continue iterating until done"

Use `tasker` when:
- you want tasks/epics/notes created without code execution
- you are mapping dependencies or sequencing first
- you want durable Codememory capture for later execution
- mutating the repo would be the wrong next step

---

## Suggested handoff rules for consistent results 🔁

For non-trivial work:

1. `orchestrator` starts
2. `explore` if 2+ modules or unclear ownership
3. `strategic-planner` when sequencing or milestone order is unclear
4. `ambiguity-analyst` when assumptions, acceptance criteria, or scope boundaries are still fuzzy
3. `librarian` if external behavior matters
5. implementation by `orchestrator` with a single writer by default
6. `verifier` for checks
7. `reviewer` final risk pass
8. `release-scribe` if PR/release text needed

Escalate to `oracle` when:
- 2+ failed fix attempts
- architecture/security/performance tradeoff is ambiguous

Planner bundle examples:

- `explore` + `strategic-planner`: when you know work is large but need file/sequence mapping first
- `explore` + `ambiguity-analyst`: when requirements are incomplete and the main need is unknown surfacing
- `strategic-planner` + `plan-critic`: when the plan exists but sequencing, feasibility, or testability still need stress-testing
- after planner fan-out, return to one writer unless explicit reservations make parallel writers safe

Planner + reservation example:

```text
git worktree add ../my_opencode-wt-planning -b feat/planning-slice HEAD
/reservation set --own-paths "docs/**" --active-paths "docs/**,agent/**" --writer-count 1
Select `orchestrator`
Delegate `explore` + `strategic-planner` to map docs and sequencing
If scope is still fuzzy, add `ambiguity-analyst`
Implement with one writer in the linked worktree
/reservation clear
```

Use this when planning work needs a real reserved path boundary before implementation starts.

---

## When not to use each agent 🚫

| Agent | Avoid when |
|---|---|
| `orchestrator` | task is trivial and single-file with no delegation need |
| `explore` | external documentation research is primary |
| `librarian` | only internal code discovery is needed |
| `oracle` | straightforward implementation is already clear |
| `verifier` | design/architecture decisions are needed instead of command execution |
| `reviewer` | no meaningful diff exists to review |
| `release-scribe` | implementation/debugging is needed rather than communication output |
| `strategic-planner` | immediate coding is required and plan is already concrete |
| `ambiguity-analyst` | scope is already unambiguous and execution can proceed directly |
| `plan-critic` | task is too early for critique (no concrete plan exists yet) |

---

## Guardrails and expectations 🛡️

- Read-only subagents must not edit files.
- Runtime hook guard blocks delegated commit/PR/edit intents for read-only subagents; keep mutating operations on the primary agent.
- Do not declare done without validation evidence.
- If blocked, return exact blocker + evidence + next best action.
- Prefer practical outcomes over over-engineering.

---

## Installation and sync notes 🔧

- Agent files are stored in this repo under `agent/*.md`.
- Source-of-truth specs live in `agent/specs/*.json` and generate `agent/*.md` via `scripts/build_agents.py`.
- Installer copies them to `~/.config/opencode/agent/`.
- `build` remains default via `opencode.json` (`default_agent: build`).
- `tasker` is an additional visible primary for planning-only Codememory capture.

Generation commands:

```bash
python3 scripts/build_agents.py --profile balanced
python3 scripts/build_agents.py --profile balanced --check
```

If agents are not visible, run:

```bash
REPO_URL="/path/to/my_opencode" REPO_REF="main" ./install.sh
opencode agent list
```

---

## TL;DR 🎉

- Keep `build` for quick tasks.
- Use `orchestrator` for complex "keep going" execution.
- Use specialist subagents for focused read-only discovery, validation, review, and release communication.
