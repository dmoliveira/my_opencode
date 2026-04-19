# Agents Cheatsheet ⚡

Fast daily reference for choosing the right agent in OpenCode.

---

## Quick pick table 🎯

| If you need... | Use this agent | Why |
|---|---|---|
| quick implementation in known files | `build` | fastest direct path |
| end-to-end delivery across multiple steps | `orchestrator` | plans, delegates, executes, verifies |
| find where logic lives in this repo | `explore` | read-only internal discovery |
| check external docs/upstream examples | `librarian` | read-only external evidence |
| sequence a complex delivery plan | `strategic-planner` | read-only milestone and dependency planning |
| surface hidden assumptions and unknowns | `ambiguity-analyst` | read-only ambiguity and risk discovery |
| decide architecture/debug strategy | `oracle` | read-only high-signal advisor |
| refine interaction quality, layout, or usability | `experience-designer` | read-only browser-first UX/UI specialist |
| validate tests/lint/build results | `verifier` | read-only execution diagnostics |
| final quality/risk review | `reviewer` | read-only ship/no-ship focus |
| critique a concrete plan for gaps | `plan-critic` | read-only feasibility and testability review |
| write PR/changelog/release notes | `release-scribe` | read-only release communication |

---

## Build vs Orchestrator 🧠

Use `build` when:
- scope is clear
- small change set
- no specialist delegation needed

Use `orchestrator` when:
- 2+ modules are involved
- you want continuous iteration until done
- you need validation + review gates before finish

---

## Recommended execution flow 🔁

For medium/large tasks:

1. Start with `orchestrator`
2. Fan out read-only mapping with `explore`
3. Add `strategic-planner` or `ambiguity-analyst` when sequence/scope is still unclear
4. Fan back in to one writer with `orchestrator`
5. Add `experience-designer` when browser-first UX polish, accessibility, or responsive review is needed
6. Run `verifier`
7. Run `reviewer`
8. Use `plan-critic` when the plan itself needs stress-testing
9. Use `release-scribe` for PR/release text

Escalate to `oracle` after repeated failures or hard tradeoffs.

Model allocation reference: `docs/model-allocation-policy.md`.
Architecture reference: `docs/agent-architecture.md`.
Tool restrictions reference: `docs/agent-tool-restrictions.md`.

---

## Prompt examples 💬

`orchestrator`:

```text
Implement this feature end-to-end, keep iterating until done, run validation, and report blockers with evidence if any.
```

`explore`:

```text
Find all files related to autopilot lifecycle transitions and summarize current state flow.
```

`librarian`:

```text
Find official docs and upstream examples for OpenCode custom agents and summarize best practice.
```

`experience-designer`:

```text
Audit this flow in-browser, capture the highest-value UX/accessibility issues, and recommend the smallest changes that make it feel clearer and calmer.
```

`verifier`:

```text
Run targeted validation for this branch and report pass/fail with root-cause hints.
```

`reviewer`:

```text
Review this implementation for correctness, maintainability, and hidden regressions. Provide ship/no-ship.
```

`release-scribe`:

```text
Draft concise PR summary and changelog bullets from current branch commits and diff.
```

---

## Useful commands 🔧

```bash
opencode agent list
```

```text
Tab -> choose agent
/agent-doctor
/agent-doctor --json
```

---

## More details 📘

See full guide: `docs/agents-playbook.md`
