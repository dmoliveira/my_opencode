# Agents Playbook 🧠

This guide explains how the custom agents in this repo work, when to use each one, and how they fit into real OpenCode workflows.

Goal: keep execution fast, safe, and low-friction while preserving the current default (`build`). ⚡

---

## Quick summary table 📋

| Agent | Type | Main job | Can edit code? | Best moment to use |
|---|---|---|---|---|
| `build` | primary (default) | Direct implementation | Yes | Small/clear tasks, quick fixes |
| `orchestrator` | primary | Lead complex multi-step delivery + delegate specialists | Yes | Medium/large tasks, end-to-end execution |
| `explore` | subagent | Internal codebase discovery and pattern finding | No | "Where is X?" / multi-module discovery |
| `librarian` | subagent | External docs and OSS evidence lookup | No | Framework/library behavior, upstream examples |
| `oracle` | subagent | High-signal architecture/debug review | No | Hard tradeoffs, repeated failed attempts |
| `verifier` | subagent | Run/interpret tests, lint, build | No | After meaningful code changes |
| `reviewer` | subagent | Risk/correctness/maintainability review | No | Before declaring done |
| `release-scribe` | subagent | PR/changelog/release notes drafting | No | Final communication and release prep |

---

## Agent model for this repo 🧭

- `build` remains the default for speed and familiarity.
- `orchestrator` is the execution lead for bigger flows.
- Specialist subagents are intentionally read-only to reduce accidental drift.
- Completion should only happen after implementation + validation + review gates pass.

Think of it as:

`orchestrator` -> delegates research/review tasks -> executes changes -> validates -> reports

---

## How to select agents (Tab menu) ⌨️

In OpenCode prompt:

1. Press `Tab`
2. Pick agent (`build`, `orchestrator`, etc.)
3. Run your prompt normally

You can verify available agents with:

```bash
opencode agent list
```

Validate agent contract + runtime wiring with:

This now also verifies orchestration policy markers in the nearest `AGENTS.md` (quickplay + WT checklist + pressure defaults).

```text
/agent-doctor
/agent-doctor-json
```

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

Use `build` when:
- scope is clear
- <= 2 files touched
- no external research needed

Use `orchestrator` when:
- cross-module task
- unknown code ownership/locations
- non-trivial validation/review needed
- you want "continue iterating until done"

---

## Suggested handoff rules for consistent results 🔁

For non-trivial work:

1. `orchestrator` starts
2. `explore` if 2+ modules or unclear ownership
3. `librarian` if external behavior matters
4. implementation by `orchestrator`
5. `verifier` for checks
6. `reviewer` final risk pass
7. `release-scribe` if PR/release text needed

Escalate to `oracle` when:
- 2+ failed fix attempts
- architecture/security/performance tradeoff is ambiguous

---

## Guardrails and expectations 🛡️

- Read-only subagents must not edit files.
- Do not declare done without validation evidence.
- If blocked, return exact blocker + evidence + next best action.
- Prefer practical outcomes over over-engineering.

---

## Installation and sync notes 🔧

- Agent files are stored in this repo under `agent/*.md`.
- Source-of-truth specs live in `agent/specs/*.json` and generate `agent/*.md` via `scripts/build_agents.py`.
- Installer copies them to `~/.config/opencode/agent/`.
- `build` remains default via `opencode.json` (`default_agent: build`).

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
