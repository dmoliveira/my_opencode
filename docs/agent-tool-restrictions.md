# Agent Tool Restrictions

This document defines explicit deny-list expectations for agent safety boundaries.

## Contract

- Subagents are read-only by default.
- Any tool listed in an agent's `metadata.denied_tools` must be disabled (`false`) in `tools`.
- Runtime enforcement targets explicit invocation intent (for example `use bash`, `functions.bash`, `"bash"`), not passive mentions like "avoid bash" or generic words such as "task".
- Primary agents may write/edit only when their tool surface allows it; planning-only primaries may remain read/write disabled.

## Deny Lists (Current)

| Agent | Denied Tools |
| --- | --- |
| `orchestrator` | none |
| `tasker` | `write`, `edit`, `webfetch`, `task`, `todowrite`, `todoread` |
| `explore` | `bash`, `write`, `edit`, `webfetch`, `task`, `todowrite`, `todoread` |
| `librarian` | `bash`, `write`, `edit`, `task`, `todowrite`, `todoread` |
| `oracle` | `bash`, `write`, `edit`, `webfetch`, `task`, `todowrite`, `todoread` |
| `verifier` | `write`, `edit`, `webfetch`, `task`, `todowrite`, `todoread` |
| `reviewer` | `bash`, `write`, `edit`, `webfetch`, `task`, `todowrite`, `todoread` |
| `release-scribe` | `write`, `edit`, `webfetch`, `task`, `todowrite`, `todoread` |
| `experience-designer` | `write`, `edit`, `task`, `todowrite`, `todoread` |
| `strategic-planner` | `bash`, `write`, `edit`, `webfetch`, `task`, `todowrite`, `todoread` |
| `ambiguity-analyst` | `bash`, `write`, `edit`, `webfetch`, `task`, `todowrite`, `todoread` |
| `plan-critic` | `bash`, `write`, `edit`, `webfetch`, `task`, `todowrite`, `todoread` |

## Validation

- `python3 scripts/agent_doctor.py run --json` verifies deny-list metadata consistency.
- `python3 scripts/build_agents.py --profile balanced --check` verifies generated markdown stays aligned with specs.
