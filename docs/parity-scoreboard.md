# Parity Scoreboard

Date: 2026-03-10
Baseline: `oh-my-opencode` at `/Users/cauhirsch/Codes/External/oh-my-opencode`

Purpose: give one fast view of current parity progress, what is intentionally different, and where to look for evidence without re-running a full audit.

## Current Scoreboard

| Area | Status | Local posture | Evidence |
| --- | --- | --- | --- |
| E1 Runtime fan-out completion | done | same-session fan-out fixed with structured child-run identity | `docs/plan/doing/agent-parallelism-parity-roadmap.md` |
| E2 Dependency-aware execution graph | done | shared `task_graph.json` drives ready lanes, blocked reasons, reservation-aware filtering, and resume | `docs/plan/doing/agent-parallelism-parity-roadmap.md` |
| E3 Agent-pool and background runtime hardening | done | `/bg` owns execution, `/agent-pool` is manual capacity/control surface | `docs/plan/doing/agent-parallelism-parity-roadmap.md` |
| E4 Orchestrator and routing upgrades | done | planner routing, fan-out/fan-in guidance, and `/autoflow` / `/autopilot` convergence aligned | `docs/plan/doing/agent-parallelism-parity-roadmap.md` |
| E5 Planning-tier productization | done | planner-tier agents visible in primary docs and checked by doctor | `docs/plan/doing/agent-parallelism-parity-roadmap.md` |
| E6 Parity scoreboard and drift checks | done | scoreboard + divergence registry + validation checks keep parity claims inspectable | `docs/parity-scoreboard.md`, `docs/upstream-divergence-registry.md` |

## Intentional Divergences

- Agent model: no upstream `sisyphus` / `hephaestus`; local split stays `orchestrator` + specialist reviewers/verifiers in `docs/upstream-divergence-registry.md`
- Hook/runtime model: local gateway-core pipeline stays canonical instead of Claude-specific compatibility layers in `docs/upstream-divergence-registry.md`
- Shell model: local runtime stays explicitly non-interactive by policy in `instructions/shell_strategy.md`

## Remaining Drift Watch

- Agent inventory and default-agent docs must stay aligned with `opencode.json`
- Runtime capability claims must stay aligned with `docs/plan/doing/agent-parallelism-parity-roadmap.md`
- Intentional divergences should be recorded in `docs/upstream-divergence-registry.md` before they are treated as closed
