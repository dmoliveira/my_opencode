# Agent Operating Contract 🛡️

This contract defines how custom agents in this repo should collaborate, when each one should be used, and what "done" means.

Primary objective: keep `build` as the default for speed, while enabling `orchestrator` and specialist subagents for high-confidence complex delivery.

---

## Agent matrix 📋

| Agent | Mode | Responsibility | Edit permissions |
|---|---|---|---|
| `build` | primary (default) | direct implementation for clear/small work | yes |
| `orchestrator` | primary | multi-step execution lead with delegation | yes |
| `explore` | subagent | internal codebase discovery | no |
| `librarian` | subagent | external docs/upstream reference research | no |
| `oracle` | subagent | architecture/debugging advisory | no |
| `verifier` | subagent | test/lint/build validation and diagnosis | no |
| `reviewer` | subagent | quality/risk review and ship-readiness | no |
| `release-scribe` | subagent | PR/changelog/release communication drafts | no |

---

## Default behavior ✅

- `default_agent` remains `build` in `opencode.json`.
- `orchestrator` is selected manually (Tab menu) for larger, multi-step work.
- Specialist subagents are read-only and support the active primary agent.
- Single-writer is the default for code edits; parallel writers are opt-in and gated.

---

## Risk-based review budget 🎚️

`orchestrator` should classify risk at task start and scale review/verification effort:

- low risk (docs/tests/small scoped edit): 1 review/fix pass
- medium risk (typical feature/refactor): 2 review/fix passes
- high risk (runtime/security/migration): 3-5 review/fix passes
- stop review cycling when required checks are green and latest review has no blocker findings

---

## Delegation triggers 🔁

`orchestrator` should delegate when:

- `explore`: unknown file ownership, cross-module impact, pattern discovery.
- `librarian`: external frameworks/libraries or upstream behavior questions.
- `oracle`: repeated failed fixes (2+), unclear architecture/security/perf tradeoffs.
- `verifier`: after meaningful code changes and before done claim.
- `reviewer`: before final response for significant/risky changes.
- `release-scribe`: when preparing PR description/changelog/release notes.

---

## Subagent budget + parallel write policy ⚖️

- Keep at most 2 concurrent subagents.
- Avoid duplicate `reviewer`/`verifier` passes on unchanged diffs.
- Allow parallel writer streams only when file ownership is clearly disjoint and reservations are explicit.
- Fall back to single-writer flow when overlap risk is non-trivial.

---

## Delegation packet contract 📦

When spawning subagents, include:

- objective and scoped ownership
- constrained file paths and constraints
- acceptance criteria and required checks
- expected output format and required evidence

---

## Completion gates (mandatory) 🚦

No done claim unless all are true:

1. requested scope has no remaining actionable items
2. required validation commands were run (or explicitly blocked with cause)
3. no unresolved high-severity blocker remains
4. verification/review steps executed when applicable

---

## Anti-loop policy 🧯

- Never respond with only another command suggestion when concrete execution is possible.
- If done criteria are satisfied and blockers are clear, emit completion once and stop.
- If user asks to continue, continue until completion gates pass or blocker contract triggers.

---

## Blocker contract 🧩

When blocked, output must include:

- exact blocker reason
- evidence (command/file/error)
- best next action

---

## Installation contract 🔧

- Source of truth for agent definitions: `agent/specs/*.json`
- Generated artifacts: `agent/*.md` via `python3 scripts/build_agents.py --profile balanced`
- Installer sync target: `~/.config/opencode/agent/`
- Installer should copy all agent markdown files during setup/update.
