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
| decide architecture/debug strategy | `oracle` | read-only high-signal advisor |
| validate tests/lint/build results | `verifier` | read-only execution diagnostics |
| final quality/risk review | `reviewer` | read-only ship/no-ship focus |
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
2. Delegate `explore` for internal mapping
3. Delegate `librarian` for external references (if needed)
4. Implement with `orchestrator`
5. Run `verifier`
6. Run `reviewer`
7. Use `release-scribe` for PR/release text

Escalate to `oracle` after repeated failures or hard tradeoffs.

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
```

---

## More details 📘

See full guide: `docs/agents-playbook.md`
