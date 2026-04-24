# Codememory Conventions

Use this file for repo-specific Codememory defaults and classification rules.

## Design goal

Keep Codememory usage consistent, durable, and easy to revise later.
The repo should use a small set of memorable rules instead of many one-off habits.

## Scope key

- default repo `scope_key`: the GitHub repo slug
- recommended value for this repo: `dmoliveira/my_opencode`
- keep worktree and branch variation inside the same repo scope unless a future repo-specific reason requires a split
- prefer a repo-local `.codememory/config.yaml` with `defaults.scope_key: dmoliveira/my_opencode` so `oc current` and related commands do not silently fall back to `local`

## Tracker split

- Codememory: internal execution state, handoffs, resumable context, durable learnings
- GitHub: issue/PR lifecycle, review, checks, merge state
- `docs/plan/...`: long-form narrative plans, specs, and historical planning artifacts

## Labels

Use short stable labels when they materially help retrieval.

Recommended repo labels:

- `docs`
- `workflow`
- `planning`
- `orchestration`
- `validation`
- `infra`
- `release`
- `agents`

Add narrower labels only when they improve queueing or retrieval enough to justify the extra taxonomy.

## Entity usage rules

### Epic

Use an `epic` for a multi-task outcome such as:

- a larger feature area
- a coordinated docs or workflow initiative
- a multi-step repo migration

Do not create an epic for a one-off small task.

### Task

Use a `task` for one actionable slice that an AI can implement or advance in one focused execution loop.

Every meaningful request that creates work must become or attach to a Codememory task.

### Session

Use one active `session` per active worktree path.

The session is the execution shell around the active task.
It should reflect real worktree reality, not an abstract plan.

### Memory

Use `memory` only for durable knowledge that should survive context loss.

Common `memory.kind` usage in this repo:

- `decision`: execution or architecture choice
- `constraint`: boundary the AI must respect
- `assumption`: current working assumption that may matter later
- `convention`: recurring repo rule worth reuse
- `idea`: future improvement or enhancement
- `issue`: durable blocker, bug, or execution problem
- `learning`: lesson from completed work
- `note`: small durable fact that does not fit the stronger categories

### Doc

Use `doc` for:

- repo markdown files
- local reference files
- remote URLs
- design notes
- runbooks

Use a linked doc when the information is too large or too structured for a short memory entry.

## What MUST be captured

Capture in Codememory when any of these are created or discovered:

- new epic or task to execute later
- durable blocker affecting execution
- decision that changes future implementation or review
- user preference that should guide later work
- assumption or convention likely to matter on resume
- useful handoff context for another AI

## What SHOULD stay out of Codememory

Avoid writing:

- trivial transient observations
- minute-by-minute progress logs
- duplicate copies of PR descriptions when GitHub already holds them
- large narrative documents that belong in markdown files

Capture the durable summary in Codememory and link the richer doc when needed.

## Human-to-AI handoff patterns

Prefer single-command intake first:

- new task: `oc add task ...`
- new epic: `oc add epic ...`
- idea: `oc report improvement ...`
- problem: `oc report error ...`
- durable rule: `oc add memory ...`
- richer brief or runbook: `oc add doc ...`

Humans do not need to prepare large YAML files for normal repo usage.
Batch imports can remain an optimization for later.

## AI-to-AI handoff patterns

Before stopping, the active AI should ensure:

- the active task exists and is accurate
- the active session reflects the current worktree state
- durable blockers or decisions are stored in Codememory
- any important markdown docs are linked as Codememory docs

The next AI should start from Codememory retrieval before reading broad historical context.

## Change management

To update or disable Codememory later with minimal effort:

- keep new repo-specific policy inside the Codememory section of `AGENTS.md`
- keep command detail in `docs/codememory-workflow.md`
- keep taxonomy detail in this file
- avoid scattering Codememory requirements across unrelated docs unless they are only short references
