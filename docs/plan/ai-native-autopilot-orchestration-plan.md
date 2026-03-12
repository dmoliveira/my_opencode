# AI-Native Autopilot Orchestration Plan

Date: 2026-03-12
Status: `proposed`
Branch: `docs/ai-autopilot-plan`
Worktree: `/Users/cauhirsch/Codes/Projects/my_opencode-wt-ai-autopilot-plan`

## Purpose

Define the next high-value runtime upgrades that let `my_opencode` run more work autonomously without waiting on humans to coordinate agents, type control commands, or manually resolve avoidable parallelism confusion.

This plan is intentionally AI-first:

- prefer runtime policy over operator reminders
- allow more same-session autonomy without sacrificing protected-main safety
- keep the canonical command hierarchy intact instead of adding new overlapping commands
- route human confirmation only for destructive, security-sensitive, or genuinely ambiguous actions

## Why this plan exists

The current stack already has strong building blocks:

- `/autopilot` objective lifecycle and stop/pause/resume controls
- `/reservation` for path ownership and writer-count controls
- `/bg` for queued/background execution
- `/rules` plus runtime rule injection
- `/delivery` as the default operator-facing workflow surface, with `/autopilot` for open-ended execution, `/autoflow` for plan execution, and legacy `/start-work` plan/todo semantics retained only as backend history
- gateway hook runtime, LLM decision runtime, and completion/validation ledgers

The remaining gap is not feature absence. It is that too much coordination is still operator-shaped instead of runtime-shaped. The next step is to let AI coordinate safe work directly.

## Problem statement

Current docs and roadmap notes point to five remaining friction points:

1. parallel fan-out is improved, but live runs can still block or fall back under same-session ambiguity
2. multiple AIs in one worktree still depend too much on predeclared human reservations
3. completion can still be chat-asserted before enough runtime evidence is assembled
4. task shaping and rule injection exist, but they are not yet a full path-aware execution policy layer
5. failed autonomous runs still escalate to the operator earlier than necessary

## Design goals

- let agents claim and sequence work without a human coordinating every slice
- allow safe same-worktree multi-agent execution when paths do not overlap inside a single non-protected linked task worktree
- serialize or reroute writes automatically when paths do overlap
- make completion evidence-driven and machine-enforced
- keep task context small and path-relevant
- recover automatically from common runtime failures before asking the user
- preserve existing worktree-first and protected-main invariants

## Non-goals

- no replacement of the canonical `orchestrator` model with persona-specific runtimes
- no removal of worktree-first protections for the primary repo on `main`
- no fully autonomous execution for destructive repo operations, secret handling, billing changes, or production-impacting actions
- no second parallel command surface that duplicates `/autopilot`, `/reservation`, `/bg`, or `/autoflow`

## Proposed architecture

### A1. Autonomous task board and claim runtime

Promote the existing plan/todo/reservation pieces into one runtime task graph that agents can mutate safely.

Core behavior:

- maintain machine-readable tasks with `pending`, `in_progress`, `blocked`, `done`, and `cancelled`
- attach each task to:
  - scope paths
  - dependency ids
  - required checks
  - delegated owner identity
  - expected artifact outputs
- allow agents to self-claim eligible tasks when dependencies are satisfied
- publish claim and release events into the existing audit/telemetry stream
- reuse existing plan/todo state semantics where possible instead of inventing a new state model, while keeping `/delivery` as the default operator-facing surface and `/autopilot` or `/autoflow` as the execution modes beneath that hierarchy

Why it matters:

- removes human micromanagement of parallel slices
- creates deterministic handoff between `orchestrator`, `explore`, `verifier`, and `reviewer`
- gives `/autopilot` a concrete execution queue instead of implicit chat intent

Suggested implementation anchor:

- extend the existing plan/todo backend semantics, `scripts/todo_enforcement.py`, and reservation state instead of creating a separate planner runtime

### A2. Same-worktree write scheduler

Introduce a scheduler that allows many readers but controlled writers inside one non-protected linked task worktree.

This is an exception lane, not the new default for broad parallel implementation. The default remains additional linked worktrees for larger or clearly separable slices. The scheduler exists for narrow cases where multiple AI runs need to cooperate inside the same task worktree without stepping on each other.

Core behavior:

- all agents may inspect any unblocked path
- writes require a short-lived lease on file or path scope
- only one writer may hold a lease for an overlapping scope at a time
- non-overlapping write leases may proceed in parallel
- before apply, verify that base content still matches the lease snapshot
- on drift, either:
  - rebase the write plan
  - requeue behind the current writer
  - downgrade the agent to plan-only mode

Why it matters:

- enables multiple AIs in one worktree without edit collisions
- reduces the need to create extra worktrees for narrow same-task collaboration, while keeping separate linked worktrees as the default for broader parallel implementation
- turns reservations from a mostly human command into an AI-usable concurrency primitive

Suggested implementation anchor:

- extend `/reservation` state and gateway guards with lease metadata, conflict classes, and pre-apply checks

### A3. Hard completion gates

Make completion a runtime decision, not a conversational one.

Core behavior:

- a task may only transition to `done` when all required gates pass
- supported gates should include:
  - validation evidence present
  - required tests or lint completed
  - claimed tasks resolved
  - required reviewer/verifier pass recorded
  - no blocking deviations left open
- if gates fail, the runtime should reopen the task and attach remediation guidance
- `/autopilot` objective completion should inherit the same gate engine

Why it matters:

- closes the reliability gap between "looks done" and "is done"
- makes autopilot safe to trust for longer runs
- aligns with the existing done-proof and validation-evidence ledger direction

Suggested implementation anchor:

- unify `done-proof-enforcer`, `validation-evidence-ledger`, `mistake-ledger`, `/post-session`, and `/doctor` around one canonical completion contract

### A4. Path-aware execution policy injection

Upgrade current pre-task shaping and rules injection into a full execution-policy layer.

Core behavior:

- load rules based on:
  - touched file paths
  - command family
  - task type
  - agent role
- inject only the minimum relevant rules into each delegated run
- support policy overlays such as:
  - docs-only
  - gateway-core runtime
  - release workflow
  - browser verification
  - refactor safety
- include explicit write policy and required validations in the injected context

Why it matters:

- cuts prompt noise and token waste
- reduces cross-domain mistakes from overbroad global instructions
- lets more decisions happen automatically because the runtime knows local policy

Suggested implementation anchor:

- deepen `rules-injector`, `agent-context-shaper`, and `task-resume-info` rather than adding a separate injector stack

### A5. Retry and recovery engine

Add a deterministic recovery pass before escalating to the user.

Core behavior:

- classify failures into retry-safe buckets such as:
  - path conflict
  - stale lease
  - failed validation
  - blocked delegation
  - low confidence
  - runtime provider failure
- choose one of a small number of recovery actions:
  - rerun serially
  - rerun with smaller scope
  - switch to a different subagent
  - request fresh verification
  - demote to plan-only mode
- only ask the operator after recovery budget is exhausted or policy forbids autonomous continuation

Why it matters:

- keeps autopilot moving instead of converting every hiccup into a human interruption
- makes long-running objective execution more realistic

Suggested implementation anchor:

- extend existing reason-code runtime, autopilot terminal states, and fallback-orchestrator logic

## Execution model

### Default runtime loop

1. derive or load a task graph for the objective
2. inject scoped execution policy for each candidate task
3. select eligible tasks whose dependencies are satisfied
4. assign read-only discovery/review work in parallel where safe
5. grant write leases only for disjoint scopes
6. run validation and review gates after each meaningful write slice
7. attempt automatic recovery for retry-safe failures
8. mark task or objective complete only when hard gates pass

### Parallelism policy

- allow many readers
- allow parallel writers only on disjoint claimed scopes
- cap concurrent subagents by policy and session pressure
- prefer one writer during `HIGH` or `CRITICAL` pressure modes
- force serial execution when lease conflict frequency crosses a threshold

### Human confirmation policy

Autopilot should not ask for confirmation when:

- the action stays within approved repo scope
- affected paths are claimed and non-overlapping
- validation and completion gates are deterministic
- failure recovery remains reversible

Autopilot should ask when:

- action is destructive or irreversible
- secrets, auth, billing, or production posture may change
- task intent is materially ambiguous after path-aware injection and retry policy

## Proposed epics

### E1 Structured task graph promotion

Goal:

- give `/autopilot` and delegated agents a shared machine-readable task graph with ownership, dependencies, and required gates

Success criteria:

- delegated runs can self-claim the next eligible task
- task state survives pause/resume and handoff
- task board state is visible through canonical status/report commands

### E2 Write lease scheduler

Goal:

- support same-worktree multi-agent editing inside one linked task worktree without overlapping-write confusion

Success criteria:

- non-overlapping writes can proceed concurrently in one linked worktree
- overlapping writes are deferred or rerouted automatically
- stale snapshot conflicts produce deterministic recovery actions

### E3 Completion gate unification

Goal:

- move completion from reminder-style enforcement to hard runtime gating

Success criteria:

- task completion is rejected when required evidence is missing
- objective completion and per-task completion share the same gate engine
- reports explain which gate blocked completion and what artifact is missing

### E4 Execution policy injector

Goal:

- inject the smallest relevant rule pack and validation contract for each delegated task

Success criteria:

- delegated runs receive path-aware rule stacks
- runtime can explain why a rule pack was selected
- irrelevant global guidance volume drops measurably

### E5 Recovery and escalation engine

Goal:

- keep autopilot in self-healing mode for common failures

Success criteria:

- common recoverable failures no longer immediately require operator input
- recovery attempts are bounded, auditable, and policy-aware
- final escalation includes precise blocker reason and attempted recoveries

## Suggested rollout order

1. E3 Completion gate unification
2. E1 Structured task graph promotion
3. E2 Write lease scheduler
4. E5 Recovery and escalation engine
5. E4 Execution policy injector

Rationale:

- hard gates improve trust fastest
- task graph and write leases unlock safe autonomy
- recovery multiplies the value of both
- richer injection lands best once the runtime has stronger scheduling and completion contracts

## Validation plan

Add scenario gates before any epic is marked complete.

- `AP1`: two read-only subagents self-claim parallel tasks and finish without operator routing
- `AP2`: two writers on disjoint scopes succeed in one linked worktree
- `AP3`: overlapping write attempt is deferred and replayed safely
- `AP4`: task completion is rejected when required validation evidence is missing
- `AP5`: objective resumes after a recoverable failure without user intervention
- `AP6`: path-aware injection selects the correct policy pack for docs, gateway-core, and release slices
- `AP7`: protected-main invariants still hold while linked-worktree autonomy remains allowed

## Open questions

- Should write leases be file-granular only, or allow glob/path-prefix scopes with automatic narrowing?
- Should task claims live in the existing plan/todo backend state store or the reservation state store?
- Should the recovery engine be allowed to spawn a fresh linked worktree when same-tree conflict pressure is too high?
- Which completion gates are mandatory by default versus opt-in by command family?

## Recommended next implementation slice

Start with E3 plus a thin E1 foundation:

- define a canonical completion-gate schema
- teach `/autopilot`, `/autoflow`, and validation ledgers to share it while reusing the existing plan/todo backend semantics
- add machine-readable task ownership and dependency fields to the existing plan/todo runtime

That gives the repo a safer autonomous core before introducing heavier same-worktree write concurrency.
