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

## Completion gates (mandatory) 🚦

No done claim unless all are true:

1. requested scope has no remaining actionable items
2. required validation commands were run (or explicitly blocked with cause)
3. no unresolved high-severity blocker remains
4. verification/review steps executed when applicable

---

## Anti-loop policy 🧯

- Never respond with only another command suggestion when concrete execution is possible.
- If user asks to continue, continue until completion gates pass or blocker contract triggers.

---

## Blocker contract 🧩

When blocked, output must include:

- exact blocker reason
- evidence (command/file/error)
- best next action

---

## Installation contract 🔧

- Source of truth for agent definitions: `agent/*.md`
- Installer sync target: `~/.config/opencode/agent/`
- Installer should copy all agent markdown files during setup/update.
