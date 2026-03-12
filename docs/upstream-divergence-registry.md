# Upstream Divergence Registry

Date: 2026-03-07
Source baseline: `oh-my-opencode` (`/Users/cauhirsch/Codes/External/oh-my-opencode`)

Purpose: keep a single, explicit record of intentional differences so parity audits do not repeatedly reopen already-decided scope.

## Status model

- `local-equivalent`: implemented with different naming or architecture.
- `intentional-divergence`: not adopted by design for this runtime.
- `deferred`: planned later, out of current execution scope.

## Agents

| Upstream capability | Local status | Local mapping / rationale |
| --- | --- | --- |
| `sisyphus` primary orchestrator persona | `intentional-divergence` | Local canonical primary is `orchestrator` (`agent/specs/orchestrator.json`) with governance-first execution contract. |
| `hephaestus` implementation specialist | `intentional-divergence` | Coverage split across local `orchestrator` + `reviewer` + `verifier`; avoids duplicate primary-runtime personas. |
| `atlas` planning persona | `local-equivalent` | Planning responsibilities are covered by `strategic-planner`, `ambiguity-analyst`, and `plan-critic` (`agent/specs/*.json`); this maps planning coverage only, not Atlas-specific runtime tool-injection behavior. |
| `metis` / `momus` / `multimodal-looker` | `intentional-divergence` | Not currently required by local operator workflows; keep agent surface compact and role-based. |

## Hook semantics

| Upstream hook name | Local status | Local mapping / rationale |
| --- | --- | --- |
| `agent-usage-reminder` | `local-equivalent` | `agent-user-reminder` (`plugin/gateway-core/src/hooks/agent-user-reminder/`). |
| `background-notification` | `local-equivalent` | `notify-events` (`plugin/gateway-core/src/hooks/notify-events/`). |
| `non-interactive-env` | `local-equivalent` | `noninteractive-shell-guard` with env-prefix injection (`plugin/gateway-core/src/hooks/noninteractive-shell-guard/`). |
| `session-notification` / `startup-toast` | `local-equivalent` | `notify-events` and runtime status commands. |
| `ralph-loop` | `local-equivalent` | `autopilot-loop` + `continuation` hooks (`plugin/gateway-core/src/hooks/autopilot-loop/`, `plugin/gateway-core/src/hooks/continuation/`). |
| `anthropic-context-window-limit-recovery` | `local-equivalent` | `context-window-monitor` + `preemptive-compaction` + `provider-token-limit-recovery`. |
| `model-fallback` / `runtime-fallback` | `local-equivalent` | `provider-error-classifier` + `provider-retry-backoff-guidance` + model routing policy commands. |
| `interactive-bash-session` | `intentional-divergence` | Local shell strategy is explicitly non-interactive by policy (`instructions/shell_strategy.md`). |
| `claude-code-hooks` | `intentional-divergence` | Local runtime uses gateway-core hook pipeline instead of Claude-specific compatibility handlers for chat/tool/compaction events; reviewed in `docs/plan/claude-code-hooks-decision-2026-03-11.md` and kept closed unless direct Claude-session transcript semantics become a requirement. |
| `category-skill-reminder` / `prometheus-md-only` / `sisyphus-junior-notepad` | `intentional-divergence` | Tied to upstream persona/task system; not part of local canonical runtime contract. |
| `atlas` runtime hook, `no-sisyphus-gpt`, `no-hephaestus-non-gpt` | `intentional-divergence` | Upstream Atlas-specific tool-time behavior injection and persona-specific model guards are not applied end-to-end locally; `task-resume-info` now mirrors a small post-task verification/reminder slice and `agent-context-shaper` adds pre-task focus shaping, but local orchestration still relies on canonical orchestrator policy plus gateway guards instead of full Atlas semantics. |
| `start-work` | `local-equivalent` | Implemented as command/runtime flow (`scripts/start_work_command.py`) instead of same-named plugin hook. |
| `anthropic-effort` | `intentional-divergence` | Local model-routing controls own effort/category policy (`/model-routing`). |
| `auto-update-checker` | `intentional-divergence` | Keep update behavior explicit via install/update workflows; no runtime auto-check hook. |

## Plugin and command surface

| Capability | Local status | Evidence |
| --- | --- | --- |
| Gateway-core as canonical plugin runtime | `intentional-divergence` | `docs/plugin-gateway-plan.md` |
| Python command bridge for slash commands | `intentional-divergence` | `docs/plugin-gateway-plan.md`, `scripts/*_command.py` |
| Multi-level parity tracking and hook expansion | `local-equivalent` | `docs/parity-injection-tracker.md`, `plugin/gateway-core/src/config/schema.ts` |

## Deferred scope

| Capability | Status | Reason |
| --- | --- | --- |
| MCP OAuth/websearch provider parity | `deferred` | Explicitly deferred by owner scope decision in `docs/plan/oh-my-opencode-parity-high-value-plan.md`. |

## Revisit triggers

- Revisit any `intentional-divergence` item only when one of these is true:
  - user asks for direct upstream behavior parity for that capability;
  - existing local flow causes measurable operator friction;
  - new architecture work requires it.
- Keep this file in sync when parity plans or hook/agent architecture decisions change.
