---
status: doing
priority: high
updated: 2026-11-02
---

# Tasker Production Protocol Reconciliation

Task: `task_122`; original proposal: `review/tasker-hardening-consolidated`
checkpoint `c106f57a`; production base: `bbb2122f` after PRs #734, #749, #750.
Depth/risk: large/high. The user authorized the separate production feature
slice after source-preserving cleanup. The archived proposal remains local-only.

## Ordered slices and dependencies

1. Define and test the production planning capability contract and native CLI
   evidence shapes. Preserve fail-closed identity, deleted-session fencing,
   immutable scope/worktree/branch provenance and session-owned record targets.
2. Extend the mandatory gateway with bounded research and stateful planning
   repairs; this depends on slice 1. Guard both admission and final rewritten
   arguments, consume revision/preview proofs, invalidate failures/deletions,
   and enforce read-only tools on Tasker research descendants.
3. Port agent/doctor/selftest and isolated harness improvements from the
   proposal; this depends on slice 2. Keep current-main routing/orchestration,
   explicit generated-tool denials and production-plugin loading. Reconcile
   artifact provenance in favor of the production triple. Use the installed
   free model catalog rather than the obsolete proposal model.
4. Run full static, deterministic and isolated live gates; review/fix changed
   diffs within the high-risk budget. Only after a replacement PR is merged,
   close old PRs #708/#709, complete the prerequisite task, update the intent
   roadmap and retire delivery state.

## Capability contract

- One OC invocation per Bash call; no shell chaining, wrappers, substitutions,
  config overrides, lifecycle overrides or arbitrary executables. Only a native
  session-ID prefix matching the actual caller may be transparent.
- Artifact adds keep exact scope/worktree/branch binding and require a matching
  scoped typed title lookup before creation. Reuse exact matches.
- Reads establish targets only from structurally valid successful scoped JSON;
  full inspections and native operation history establish repair proofs.
- Non-status task/epic metadata updates require a reason and observed revision.
  Task cancellation stays denied: native task claims do not increment task
  revision, and cancellation clears claims without an atomic unclaimed
  predicate. Queue snapshots cannot close that race. Lifecycle changes remain
  execution-agent work. Backend optimistic concurrency guards metadata updates.
- Planning links are parent-of (epic/task), depends-on (task/task), about
  (memory/task|epic|doc); reject duplicate and lifecycle/session relations.
  Unlink requires full inspected planning-edge provenance.
- Archive/restore is only for inspected unreferenced memory/doc targets with
  complete scoped link evidence and a successful native preview. Apply binds
  operation, target, reason and hash, and consumes the proof on attempt.
- SQLite migration is a one-shot capability after a native doctor proves a
  safe missing/empty/adoptable/pending worktree-local SQLite store. Unsafe,
  dirty, newer, unknown and non-SQLite states remain blocked.
- At most two research calls per user request, only explore/librarian with a
  bounded explicit read-only packet. Descendants cannot execute Bash, mutate,
  delegate or validate. Final routing/command mutations cannot broaden approval.

## Native CLI findings

`get --view full` exposes scope/type/status but not revisions or claims.
`history` exposes applied operations and resulting revisions; `queue` exposes
active-session claim evidence. Recovery preview returns operation/target/reason,
current revision and plan_hash. A missing SQLite doctor still exits zero and
reports status=error, backend=sqlite, parse_ok=true, migration_state=missing;
a process exit code alone is insufficient authorization evidence.

## Named validation

- Targeted gateway policy, state-machine and real-OC integration tests.
- Ruff on touched Python; generated-agent/doctor and writer-inventory checks.
- `npm --prefix plugin/gateway-core run lint`, build, and full test suite.
- `make -C <delivery-worktree> validate`, `make selftest`, installer smoke,
  configured `pre-commit run --all-files`, and `git diff --check`.
- Isolated live sandbox loading the actual production plugin: bootstrap,
  research-before-persistence, typed graph/dependency, duplicate and refusal
  scenarios. Record that host state is unchanged and disposable stores removed.
- Current-main/overlap and required CI checks immediately before PR-only merge.

## Plan-review resolutions

- Add a Tasker `tool.execute.before.final` dispatch immediately before the
  existing last dependency-authorization check. No hook runs after that final
  dependency check. Bind final arguments/call/session and reject target changes.
- Resolve parent chains using always-on `session.created` parent metadata with
  `client.session.get` fallback, bounded depth/cycle checks and fail-closed
  unknown lineage. Keep research ancestry restrictions after parent deletion.
- Cache typed evidence per session and mutation generation with bounded TTL and
  size: exact lookup IDs/full records, history revision, queue claim state,
  complete link inventory, doctor path/state, and recovery operation/target/
  reason/hash/revision. Initial and final gates both check evidence. Final
  admission consumes proofs before execution; failure cannot restore them.
- Reads may assemble complementary evidence in one mutation generation. Any
  mutation attempt, new user request, compaction or deletion invalidates proofs.
  Recovery applies consume previews even on failure. Concurrent mutation finals
  serialize through one in-flight admission; reads never confer write authority
  from missing fields or untyped/error output.
- Doctor paths must resolve to the bound worktree-local `.codememory` config and
  database, with no symlink escape; only explicit known safe SQLite states grant
  one migration attempt. A fresh doctor is required after any attempt.
- Native list/find rows expose `display`, not full title/type/provenance. Typed
  lookups therefore require full inspection of every bounded candidate before
  add; complete link inventories require full link inspections before proving
  a target unreferenced. Truncated results are not absence evidence.
- Sandbox success requires a production-plugin audit marker and a deliberately
  blocked unsafe call, plus host-state hashes and disposable cleanup checks.

## Backend atomicity decision

The installed Codememory implementation atomically rejects referenced-record
archive/restore at both preview and apply and checks revision/hash; its SQLite
implementation is `src/db/sqlite.rs:11158-11315`. This supports guarded recovery
without changing another repository. In contrast, task transition at
`10939-11010` clears active claims and lacks an atomic unclaimed precondition.
The reconciled production contract deliberately keeps all task/epic/session
lifecycle transitions, including `cancel`, denied; the proposal's cancellation
exception is rejected rather than relying on an unsafe queue-read race.
