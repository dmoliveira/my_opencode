# Tasker Production Planning Protocol

Tasker owns planning artifacts and bounded research. Execution agents own code,
Git/GitHub delivery and task/epic/session lifecycle. Agent source is
`agent/specs/tasker.json`; generated Markdown and the sandbox must agree with it.

## Authority and transport

The mandatory `tasker-command-gateway` remains active when optional hooks are
disabled or reordered. It authorizes the initial invocation and rechecks final
arguments after all ordinary hooks, immediately before the existing final
dependency-authorization boundary. Post-execution evidence must match that
session, call and argument binding and a successful native exit status.

- One session binds an immutable scope/worktree/branch triple from the caller.
- Every artifact add carries that exact triple. Bash uses the canonical bound
  worktree, an approved scalar argument schema and a bounded timeout. A different
  workdir or a late rewrite cannot select another backend.
- Bash contains one OC invocation. No shell chaining, arbitrary executables,
  wrappers, configuration selection or overrides are authorized. Only an exact
  `OPENCODE_SESSION_ID` assignment matching the native caller is transparent.
- Successful scoped lists/finds establish record membership. Full records are
  required before metadata/edge repairs; wrong-scope, malformed and error replies
  never grant write authority. Native `get` does not expose revisions: metadata
  updates use the latest applied revision from native `history` plus a reason.
- Evidence is session-local, generation-bound, size-limited and expires after
  two minutes. Mutation attempts consume it before execution. Failed operations,
  new user requests, compaction and deletion cannot restore an earlier proof.
  Backend calls serialize final admissions; a late response from an older
  generation cannot mint authority.

## Planning capabilities

| Operation | Required evidence |
| --- | --- |
| Add task/epic/memory/doc | Matching scoped typed title lookup; full inspection of every returned candidate; exact matches must be reused |
| Non-status task/epic metadata update | Full scoped record, native history revision, reason and exact expected revision |
| Planning link | Full endpoints, complete scoped link inventory and inspected exact edge/target candidates; no duplicate |
| Unlink | Full inspected planning edge and endpoints, exact ID and reason |
| Memory/doc archive or restore | Full scoped target, successful native preview, exact operation/target/reason/hash; apply proof is one-shot even on failure |
| SQLite bootstrap | A native doctor proving a safe worktree-local missing/empty/adoptable/pending SQLite store and canonical owned paths; one attempt, then fresh doctor |

Only parent-of (epic/task), depends-on (task/task) and about
(memory/task-or-epic-or-doc) are planning edges. Session and execution relations
are excluded. Link absence uses a complete inventory of at most 1000 rows;
search absence uses at most 100 rows. A response at the requested limit is not
complete. Native edge/target display selects candidates, so unrelated edges do
not require hundreds of full reads.

Native archive/restore rejects referenced targets in its transaction at both
preview and apply, and checks the plan hash/revision. Overrides remain forbidden.
Task cancellation is deliberately excluded: current native claims do not bump
task revision, and cancellation clears claims without an atomic unclaimed
predicate. Queue inspection plus an expected revision cannot close that race.
All task/epic/session lifecycle therefore stays with execution agents.

Bootstrap accepts only the exact known SQLite state/code pairs and a native
semantic error/readiness report, not exit zero alone. The database and config
must be inside the canonical bound worktree's `.codememory`, owned by the
current account, non-symlinked and not group/world writable. Unknown ownership,
unsafe/dirty/newer/unknown schema and non-SQLite stores fail closed.

## Bounded research

At most two attempts are admitted per user request, only to `explore` or
`librarian`, before artifact persistence. Existing child sessions cannot be
resumed through this capability. The task prompt is a bounded JSON object with
exactly `objective`, `paths`, `acceptance`, `checks`, `evidence`, `constraints`.
Paths are 1-8 constrained relative paths or credential-free HTTPS references;
text fields are at most 2000 characters. Constraints are exactly:

```json
["read-only", "no writes", "no Codememory", "no delegation", "no tests or builds", "no git or gh"]
```

Optional routing/context hooks preserve the validated packet and explicit role.
Only an inert native trace header may precede it, followed by the mandatory
read-only boundary. Arbitrary prefix/suffix instructions or routing changes are
rejected at the final gate. Parent ancestry is tracked independently of optional
hooks, with native session lookup fallback, bounded depth and cycle checks.
Descendants cannot use Bash, mutation or further delegation, including after a
parent is deleted. Unknown lineage cannot grant mutating tools. Persistence
waits for successful completion of admitted research.

## Reconciliation of PRs #708 and #709

- Keep the source planning/research, doctor, pure setup/launcher separation,
  environment isolation, duplicate-run qualification and bounded recovery ideas.
- Keep current production identity/deleted-session fencing, record ownership,
  exact artifact provenance, model routing and final dependency binding.
- Replace fixture-only authorization with the actual production plugin. Retain
  explicit denied tools, including `write` and `todoread` from PR #750.
- Reject the old ban on provenance flags for artifacts: those flags bind the
  planning target, not an execution-session creation request.
- Reject the cancellation exception because the backend cannot atomically
  enforce its unclaimed precondition. No equivalent unsafe status-setting path
  is introduced.
- Keep the original local-only checkpoint `c106f57a` and its verified recovery
  artifacts as source history; implement this protocol on current production.

## Validation

`make tasker-production-live-smoke` runs real OpenCode, native Bash/Read/Task tools
and Codememory against disposable workspaces and a controlled localhost provider.
It exercises bootstrap, real research, graph edits, revision checks, native
referenced-record rejection, unlink/archive/restore, duplicate rejection and
forbidden lifecycle/shell/workdir attempts. It requires audit markers from the
actual gateway and verifies the victim database was not created, host Codememory
was unchanged and the temporary root was removed. No provider account/key is
required; the provider controls tool selection, not authorization or backend
results.

The full gateway lint/build/test, Python validation, generated-agent/doctor,
writer-inventory, selftest, installer and pre-commit gates remain required.

## Discovery and lifetime bounds

Tasker's own filesystem discovery is canonicalized inside its bound worktree.
Research children receive a signed, parent-bound read authority in their native
initial prompt. The mandatory gateway verifies it and authorizes actual native
read/list/glob/grep targets against the packet's literal files/directories;
absolute host paths, traversal and escaping symlinks are rejected before both
admission and final execution. Directory searches are bounded and fail closed
when a linked or oversized tree cannot be proven inside the grant. Network
research tool requests must name an exact declared credential-free HTTPS
reference; unconstrained web search is not granted by this protocol.

A missing sandbox cannot authorize Bash or task calls, including backend reads.
Inactive, idle sessions with no owned admission or pending research may be
removed from the 512-entry heavy-state LRU. Resumption requires a fresh real
user request and fresh inspection; synthetic continuations cannot renew an
evicted request's budget. Native terminal tool-error/cancellation events retire
only a finalized matching session/call and owned argument binding. No timer
silently releases a potentially active operation.

Read grants use literal relative files or directories, not wildcard grants.
To use native glob/grep, grant the containing directory; the tool query may
then filter within it. File-only grants permit direct reads of those files.
