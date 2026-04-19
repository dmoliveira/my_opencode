# Agent Architecture

This document is the single reference for agent structure, role boundaries, and execution workflow.

## Inventory

| Agent | Mode | Can Edit | Cost Tier | Default Category | Primary Use |
| --- | --- | --- | --- | --- | --- |
| `build` | primary | yes | cheap | `balanced` | direct implementation for clear, scoped work |
| `orchestrator` | primary | yes | expensive | `balanced` | end-to-end multi-step execution |
| `tasker` | primary | contract-only | cheap | `writing` | Codememory-backed planning capture without implementation |
| `explore` | subagent | no | free | `quick` | internal codebase discovery |
| `librarian` | subagent | no | cheap | `balanced` | external docs/upstream lookup |
| `oracle` | subagent | no | expensive | `critical` | architecture/risk advisory |
| `verifier` | subagent | no | cheap | `quick` | test/lint/build diagnostics |
| `reviewer` | subagent | no | expensive | `critical` | final quality/risk review |
| `release-scribe` | subagent | no | cheap | `quick` | PR/changelog/release drafting |
| `strategic-planner` | subagent | no | cheap | `deep` | sequencing and milestone planning |
| `ambiguity-analyst` | subagent | no | cheap | `deep` | assumptions/unknowns analysis |
| `plan-critic` | subagent | no | expensive | `critical` | feasibility and testability critique |

Metadata source of truth: `agent/specs/*.json`.

## Modes

- `primary`: user-facing lead agent; capabilities depend on its tool surface, so some primaries execute code while others stay planning-focused by contract.
- `subagent`: read-only specialist used for focused discovery/research/review/verification.

## Execution Workflow

1. Select lead agent (`tasker` for planning capture, `orchestrator` for complex execution).
2. Set routing category by effort (`quick|balanced|deep|critical`).
3. Either capture/update planning artifacts only (`tasker`) or delegate focused subagents for execution work (`orchestrator`).
4. Implement and validate in small increments when the selected primary is an execution agent.
5. Run verifier + reviewer gates before completion for implementation work.
6. Produce release communication artifacts when needed.

Task-graph-aware default:

- fan out read-only discovery and planning first
- fan back in to one writer for implementation by default
- use the shared task graph to inspect ready lanes, blocked reasons, and resumable work before opening more execution paths

## Delegation Guidance

- Discovery unknowns: `explore`
- External behavior uncertainty: `librarian`
- Hard architecture/debug tradeoffs: `oracle`
- Check execution/failure triage: `verifier`
- Final correctness/safety pass: `reviewer`
- Release text and summaries: `release-scribe`
- Planning and sequence design: `strategic-planner`
- Assumption and ambiguity surfacing: `ambiguity-analyst`
- Plan risk and missing gates: `plan-critic`

## Tool Restriction Contract

Read-only agents must keep write/edit disabled and must not be granted escalation via delegation loops.
Canonical contract and per-agent deny lists: `docs/agent-tool-restrictions.md`.

## Model Routing Contract

Model allocation and fallback policy is documented in `docs/model-allocation-policy.md`.
