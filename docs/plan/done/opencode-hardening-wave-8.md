---
status: done
priority: high
updated: 2026-07-28
---

# OpenCode Hardening Wave 8

Date: 2026-07-27
Runtime session: `ses_067d2e945ffe5mebe04ifDBZTc`
Branch: `perf/opencode-hardening-wave-8`
Codememory: `epic_3`, discovery `task_40`, planned implementation `task_41` through `task_47`
Tmux sandbox: `ai-oc-hardening-wave8`

## Objective

Run one evidence-led iteration across validation hermeticity, model-harness
containment, gateway state durability, shared configuration transactions, and
managed developer tooling. Adopt no new plugin or MCP. Add one exact-pinned
local CLI only if its independent supply-chain slice passes every authority and
isolation gate. Prove the final stack on realistic Python and Node projects with
exact `openai/gpt-5.4-mini`.

## Classification And Review Budget

- Depth: `large`.
- Risk: `high` because the slice changes shared config persistence, cross-runtime
  state writes, process termination, output-directory authority, and executable
  supply-chain policy.
- Review budget: three to five changed-evidence review/fix passes. Stop only when
  every required check is green and the latest critical review has no blocker.
- Execution: one writer. Read-only discovery, verification, and review may fan
  out to at most two subagents.

## Alignment And Baseline

- `origin/main` and the worktree started at `f1a5297`; no open PR or issue
  overlapped the work.
- Primary-main user overrides remain outside this branch and must be preserved.
- Baseline in tmux passed: Python `128/128`; gateway `761/761`; lint, build,
  `make validate`, and `make selftest` all exited zero.
- Baseline exposed a hermeticity defect: `make selftest` changed only
  `docs/plan/docs-automation-summary.md` by replacing its timestamp.
- `docs/plan/current-roadmap-tracker.md` contained committed merge markers. The
  planning slice preserves the deduplicated union of both task lists and adds
  one Wave 8 pointer.
- Owner-local evidence is under `runtime/harness-wave-8/`. Live downloads and
  model-backed evidence are owner-host evidence, not ordinary CI evidence.

## External Tool Decision

Official OpenCode documentation and the current ecosystem were reviewed on
2026-07-27. Community plugins remain unsandboxed and receive broad client,
workspace, and shell authority.

- Reject/defer DCP, Morph, PTY, notifier, background-agent, worktree, Braintrust,
  and WakaTime plugins. They fail authority, egress, mutable dependency,
  maintenance, overlap, or measured-value gates.
- Keep hosted MCPs disabled. Keep exact-pinned Playwright disabled and on demand.
- Retire `gh-dash`, `ripgrep-all`, `tree-sitter-cli`, and Lefthook from the
  managed required/automatic devtool surface. They are interactive, redundant,
  corpus-specific, parser-authoring-specific, or duplicate `pre-commit`.
- `ast-grep 0.45.0` is the sole adoption candidate. The Apple Silicon release
  archive SHA-256
  `ec2e3680f4f84c68b48420bcca01d21389787c7318b52083dde6f46ac12ad946`
  and extracted `ast-grep` SHA-256
  `92b5c91bad81864bc2f9ee223e9cf8579abc201fe4d1027b092b0227c472977b`
  are locally recorded integrity anchors. Source tag commit
  `5d439d9bb92d5ba9e7dba8343348c4597e7a1fbc` is separate source metadata;
  absent a vendor signature or reproducible-build proof, it does not attest
  binary-to-source correspondence.
- On one Apple Silicon host, a recorded 20-run warm trial observed about 96 ms
  p95 on the recorded corpus. The trial also found two AST matches versus four
  text matches, isolated one rewrite, left tracked query state unchanged,
  forwarded no host-sensitive environment, and left zero survivors. This is
  value evidence, not a cross-host performance or provenance guarantee.
- The deprecated `sg` launcher is not adopted; only `ast-grep` is eligible.

Primary external references:

- <https://opencode.ai/docs/ecosystem/>
- <https://opencode.ai/docs/plugins/>
- <https://opencode.ai/docs/tools/>
- <https://github.com/ast-grep/ast-grep/releases/tag/0.45.0>
- <https://ast-grep.github.io/guide/quick-start.html>

## Dependency Sequence

```text
task_40 reviewed plan
  -> task_41 hermetic validation
  -> task_42 contained model harness
  -> task_43 atomic gateway state
  -> task_44 transactional shared config
  -> task_45 devtool retirement
  -> task_46 exact ast-grep supply-chain slice
  -> task_47 full validation, audit, PR, merge, and cleanup
```

Each implementation task gets a focused validated commit before the next starts.
The ast-grep slice has the explicit terminal outcomes defined below and may be
deferred without weakening tasks 41-45.

## Decisions

### 1. Hermetic validation (`task_41`)

- Add fixture-root support to the release-index generator.
- Run release-index and docs-summary generation only against a disposable
  fixture in selftest. Keep the real repository sync check read-only.
- Inject a fixed generation timestamp in fixture tests and require two repeated
  generations to be byte-identical.
- Never restore generated files after selftest as proof. Two consecutive
  selftests must leave tracked status and a tracked-file hash manifest unchanged.
- Resolve roadmap merge markers by retaining the deduplicated union.

### 2. Contained model harness (`task_42`)

Output authority:

- The selected output path must be absent and a strict descendant of the
  selected repository's `runtime/` directory. Each invocation creates it as
  `0700` and writes a fixed marker. The harness never recursively replaces or
  deletes a caller-selected existing path.
- Reject repository root, runtime root, outside paths, existing paths, symlinks,
  and unsafe ancestors before creation. Victims remain unchanged.
- The marker is an accidental-deletion/ownership guard, not protection against
  a malicious concurrent same-UID process.

Process and artifact bounds:

- Replace `communicate()` and line-based readers with fixed-chunk byte capture.
- Record per-stream `total_bytes` and `truncated` fields. Protocol and JSON
  consumers fail closed whenever required output was truncated.
- One monotonic deadline covers wait, TERM, KILL, post-exit drain, descriptor
  close, and thread join. Inherited pipe holders cannot extend the deadline.
- Artifact inspection uses no-follow metadata checks and explicit file-count,
  per-file, and aggregate byte limits; symlinks and special files fail closed.
- Process-group containment is supported on Darwin/Linux. Unsupported platforms
  fail before spawning until a separate implementation exists.
- Tests include no-newline floods, TERM-resistant children, inherited open
  pipes, path attacks, and zero surviving owned processes.

### 3. Atomic gateway state (`task_43`)

Normative Python/TypeScript protocol:

- Fixed state path `.opencode/gateway-core.state.json`; fixed adjacent lock
  directory `.opencode/gateway-core.state.json.lock`.
- Acquire with atomic `mkdir`, require `0700`, write a unique owner token, poll
  to one shared monotonic timeout, and never reclaim stale locks automatically.
  Release only after token and lock identity still match.
- Bypass caches and read raw JSON only after lock acquisition. Malformed or
  non-object state fails before mutation.
- Update only the writer-owned domain while value-preserving `activeLoop`,
  `conciseMode`, unknown top-level fields, and unknown nested domain keys.
- Reject unsafe parent directories, symlinks, hardlinks, non-regular targets,
  ownership mismatches, and stale locks without changing victims.
- Stage a unique `O_EXCL` `0600` regular file, flush it, atomically replace the
  state, and sync the directory. Replacement is the commit point; a later sync
  error reports `committed_durability_uncertain`.
- Supported hosts are Darwin/Linux. Other platforms fail closed.
- Gateway doctor reports lock presence or acquisition timeout plus manual
  remove-after-owner-stop guidance; it does not claim PID-authoritative
  staleness. Automatic recovery and PID authority remain deferred.
- A real Node/Python barrier test repeatedly updates disjoint domains, retains
  unknown sentinels, observes only valid JSON, leaves no lock, and finishes
  within a fixed deadline.

### 4. Transactional shared config (`task_44`)

- Introduce `edit_layered_config(mutator)`. It acquires one stable per-user
  layered-config namespace lock before candidate discovery, then acquires
  deduplicated canonical-target locks in sorted order. All acquisition and
  pre-mutation retries share one validated finite monotonic deadline. Locks use
  private owner tokens, are released in reverse order, and are never reclaimed
  automatically.
- Snapshot every candidate's presence or absence, every loaded layer, the full
  symlink chain (identity plus raw link text), canonical parent identity, and the
  final target. A lexically present broken or unsafe higher-priority candidate
  fails closed rather than falling through. Re-resolve after target locking;
  release target locks and retry if canonical lock identities changed. Invoke a
  non-reentrant mutator exactly once only after a stable re-resolution, and do
  not rerun it after any post-mutation stale-snapshot failure.
- The single-file API passes one deep-copied merged effective configuration to
  an in-place mutator that returns `None`; successful candidate/lock retries
  happen before that exactly-once call. It persists the resulting effective
  configuration to the selected write layer, matching existing behavior.
  `edit_config_batch(participants)` declares direct-file participants and their
  in-place mutators up front. It resolves and locks every participant before
  invoking mutators in declaration order, stages all changed files, replaces in
  sorted canonical-path order, stops after the first replacement/sync failure,
  and returns an ordered per-file result. The layered wrapper may include direct
  sidecars in the same coordinator; a sidecar alias of the layered write target
  is rejected before any mutator runs.
- Read through verified descriptors with strict UTF-8 and byte bounds. JSONC
  removal preserves token separation and rejects unterminated comments,
  duplicate keys, non-finite or unsafe numbers, non-object roots, and malformed
  input. A changed JSONC file may normalize to strict JSON; an exact semantic
  no-op preserves bytes, inode, mode, and timestamps and creates no target or
  stage.
- Config input and serialized output are capped at 4 MiB. Integers outside
  `[-9007199254740991, 9007199254740991]`, non-finite numbers, and integral
  floats outside that range are rejected.
- Stage and flush a unique `O_EXCL` `0600` regular file in each canonical target
  parent, revalidate the entire discovery/layer/link/target snapshot, atomically
  replace the canonical target while preserving intentional symlinks, and sync
  each unique parent directory.
- Reject hardlinks, non-regular targets, unsafe parents, ownership mismatches,
  malformed current config, and stale snapshots.
- Inventory writers by destination path, not import syntax. Every writer that
  can resolve to a shared OpenCode config candidate must migrate. Exempt state
  files use a checked static allowlist; canonical aliases cannot bypass the
  transaction. Provisioning symlink writers are explicitly classified and use
  the same namespace serialization. A checked static inventory fails on partial
  migration.
- The closed production manifest names `auto_slash`, `browser`, `budget`,
  `config`, `gateway`, `hooks`, `keyword_mode`, `kvforge_discovery`, `mcp`, `notify`,
  `plan_execution_runtime`, `plugin`, `policy`, `post_session`, `quality`,
  `rules`, `stack_profile`, `telemetry`, and `tmux` as transactional writers;
  `setup_dual_opencode.sh` and `setup_local_dev_symlinks.sh` are serialized
  provisioners. `model_routing` and gateway sidecar writers use direct-file
  transaction participants and reject aliases of the layered target. Exact
  fixture/state/sidecar exemptions are callsite-scoped.
  Static discovery must equal this manifest and fails on any unmatched shared
  candidate sink.
- Replacement is the commit point. A directory-sync failure after replacement
  reports `committed_durability_uncertain`, never generic rollback. Errors carry
  stable reason, phase, committed, durability, lock-release, cause, and secondary
  reason fields.
- Multi-file operations acquire canonical locks in sorted order, stage every
  changed file first, and compose duplicate direct participants in declaration
  order on one shared object before staging. Layer discovery deduplicates
  canonical aliases while preserving the highest-precedence lexical layer; this
  explicitly supports the shipped user `opencode.json` -> bundled repository
  `opencode.json` symlink topology without replacing either symlink. Incompatible
  layered/direct aliases fail before mutation. Multi-file operations
  provide serializable isolation among participating writers plus per-file
  atomicity, not crash atomicity or lock-free-reader atomicity. Results include
  per-file commit/durability state; a strict replaced subset is `partial_commit`.
- Deterministic multiprocessing tests cover disjoint nested updates, deletion
  versus update, same-key serialization, crash-before-replace, malformed state,
  symlink-chain and priority changes, reverse lock order, victim safety, finite
  deadlines, release failures, partial commits, and no-op byte stability.

### 5. Retire unnecessary devtools (`task_45`)

- Remove mutable automated Homebrew and GitHub-extension installation. Unmanaged
  host tools become observation-only with manual guidance.
- Remove `gh-dash`, `ripgrep-all`, `tree-sitter-cli`, and Lefthook from doctor,
  install-all, usage, and current operator guidance.
- Canonical hook installation uses exact local `pre-commit` only with a finite
  deadline. Historical Lefthook files may remain compatibility artifacts but
  are no longer required or invoked.
- Playwright CLI remains exact, explicit, and outside `install all`.
- Tests prove no call to `brew`, `gh`, npm, or npx from the retired/all paths.

### 6. Exact ast-grep (`task_46`)

- `/devtools install ast-grep` and `install all` support only Darwin arm64 in
  this slice. Unsupported tuples fail before creating cache, bin, or attestation
  paths. Installation refuses root/elevated execution and requires pre-existing
  absolute injected cache/bin roots with `uid == euid != 0`; roots must be
  current-user-owned, mode `0700`, non-symlink directories. Root
  descriptors use `O_DIRECTORY|O_NOFOLLOW`, stay open through commit, and are
  rechecked for pathname identity, ownership, and mode before every
  download, extraction, execution, and publication boundary. Link count `1`
  applies to regular files, not directories.
- Use exact asset name/URL plus hard-coded archive and binary SHA-256 values.
  A stdlib-only `python -I -B -S` child receives only a pre-opened archive FD,
  uses no proxies/cookies/authorization or credential-bearing environment, and
  permits at most three HTTPS/443 redirects across exact `github.com` and
  `release-assets.githubusercontent.com` hosts. A 60-second parent deadline
  bounds the child; socket operations use a 10-second timeout.
- Bound archive bytes, entry count, compressed/uncompressed size, compression
  ratio, and download time. Reject duplicate, encrypted, absolute, traversal,
  symlink, device, socket, and other special entries. The exact pinned archive
  profile contains ordered regular entries `sg` and `ast-grep`, is at most 10
  MiB, expands to at most 64 MiB total/per member, and has a maximum ratio of
  10. Core ZIP has no portable hardlink type, so hardlink safety is by
  construction: never call extraction APIs, stream only `ast-grep` into a fresh
  `O_EXCL` regular file, and require `st_nlink == 1`.
- Extract only `ast-grep`; never install or execute deprecated `sg`. Verify the
  staged binary hash, exact `ast-grep 0.45.0` output under a minimal environment,
  and a second post-execution hash before installation. The executable stage is
  adjacent to the destination in the retained bin root, created
  `O_EXCL|O_NOFOLLOW` as `0600`; ordering is write, hash, `fchmod(0700)`, `fstat`,
  `fsync(stage_fd)`, then execute and publish. Version execution
  has a 10-second process-group deadline, bounded 64 KiB stdout/stderr capture,
  TERM/KILL/reap/drain handling, and a zero-survivor requirement. The retained
  stage FD and pathname identity must match before and after execution and again
  immediately before publication. Active malicious same-UID mutation remains
  outside the supported threat boundary.
- Refuse existing symlink, hardlink, non-regular, unmanaged, or unattested
  executables. Do not replace a user-managed `ast-grep`.
- Reject symlinked or identity-changed cache/bin roots before download,
  extraction, attestation, or installation.
- Installer, recovery, idempotence checks, and doctor coordinate through one
  stable `0600` lock inode using a bounded advisory lock; the lock is never the
  removable journal. Doctor performs no write and reports `busy` if the lock is
  unavailable. Before first install, an absent-lock doctor verifies all fixed
  install names absent, rechecks lock absence, and returns `missing`; a lock that
  appears yields retry/`busy`. Before staging, create and sync a separate fixed-name `0600`
  transaction journal whose schema never supplies paths. Publish
  with fd-relative Darwin `renameatx_np(..., RENAME_EXCL)` only; unsupported
  filesystems fail closed with no `os.replace` fallback. Sync the bin directory,
  publish/sync a strict `0600` attestation with the same exclusive primitive,
  then remove/sync the transaction journal. A valid journal supports crash
  finalization; fixed basenames are always authoritative. Any failure after
  executable publication reports separate `committed`, `complete` or
  `recovery_required`, and `durability` fields rather than rollback.
- The recovery table is explicit: no binary/attestation/journal is fresh; exact
  binary plus exact attestation is an offline write-free no-op; journal plus no
  binary resumes pre-publication; journal plus exact binary and no attestation
  finalizes; journal plus exact binary and exact attestation removes the journal.
  Every other combination, malformed/oversized journal, or destination or
  attestation appearing during install is an exclusive-publication refusal.
  Unmanaged or unattested binaries are never adopted solely because bytes match.
  Archive, executable-stage, and attestation-stage files use fixed temporary
  basenames. Under the stable lock, a valid journal authorizes validation plus
  cleanup/restart of only those names followed by directory sync. Without a
  valid journal, any fixed temporary artifact is unmanaged and causes refusal.
- Attestation is evidence, not the trust anchor. Doctor never downloads or
  executes the binary; it opens binary/attestation through retained root FDs,
  validates bounded schema/ownership/mode/link/identity state, and rehashes the
  installed executable against the hard-coded binary digest on every call.
- Tests use a local fixture archive and subprocess-level write audit with all
  roots injected into a temporary directory. PATH sentinels prove brew, gh, npm,
  and npx were never invoked. No host-global write is allowed. Fault injection
  covers redirects, archive bounds/types, root and destination swaps, exclusive
  publication, every sync boundary, stable-lock/journal races, transaction
  recovery, concurrent installer/doctor barriers, offline idempotence, staged
  execution hangs/output floods/substitution, first-install absent-lock doctor
  barriers, every journal/temporary-artifact combination, and doctor tampering
  during hash.
- Replay the recorded fixture precision/rewrite checks and a bounded performance
  smoke. The Darwin-arm64 owner-host cell performs a fresh production download
  into temporary injected roots, measures secret-environment forwarding and
  surviving processes, verifies a second offline idempotent install, and proves
  cleanup. It records the literal asset URL, redirect hosts/count, exact archive
  profile and hashes, documented inherited FDs only, zero synthetic secret
  names/values in the child environment, successful doctor rehash, zero
  surviving PIDs, and no writes outside injected roots. The second install runs
  with network disabled and must preserve inode/bytes with no child, execution,
  or write. Performance is informational; exact two-vs-four precision and
  isolated rewrite behavior are the value pass criteria.

The exact archive manifest is part of the gate, not only a set of loose limits:
ordered `sg` then `ast-grep`; Unix regular mode `0100755`; deflate method `8`;
flags `0`; no comments; exact reviewed extra bytes; `sg` size/compressed/CRC
`413008`/`172629`/`0x8d0a6976`; `ast-grep` size/compressed/CRC
`52074976`/`7938787`/`0xabd6d0af`; aggregate uncompressed/compressed bytes
`52487984`/`8111416`. Ratio checks use integer arithmetic and streamed byte/CRC
and hash checks confirm metadata claims.

Implementation slices are policy/root/lock gates, downloader/archive authority,
bounded staged execution, exclusive publication/recovery, doctor/idempotence,
and owner-host replay. Adoption edits stay uncommitted until the final gate. If
any slice or live cell fails or remains blocked, restore the task-45 baseline and
record `DEFERRED` with no installer, guidance, managed binary, or attestation.

`task_46` has two terminal outcomes:

- **ADOPTED:** every deterministic authority test and the required Darwin-arm64
  owner-host cell pass. Ast-grep-specific closure gates apply.
- **DEFERRED:** any authority/value cell fails or remains blocked. No ast-grep
  installer, managed binary, attestation, or adoption guidance lands. Closure
  verifies tasks 41-45 and confirms no new managed executable exists.

A `BLOCKED` cell can never count as `ADOPTED`.

Task 46 outcome: **ADOPTED** on 2026-07-28. The deterministic authority suite,
native Darwin `RENAME_EXCL` checks, sandbox-confined production download, and
network-denied offline owner-host replay passed. Sanitized evidence is recorded
at `runtime/harness-wave-8/task46/owner-host-report.json` during validation; the
runtime artifact is intentionally ignored and is re-created by the live gate.

Task 47 outcome: **PASS** on 2026-07-28. All five manifest-guarded closure
bundles, dual-Node matrices, package parity, provider and gateway runtime probes,
ast-grep replay, and exact-model Python/Node E2E passed on committed candidate
`feabc6f`. The tracked closure record is
`docs/opencode-hardening-wave-8-audit-2026-07-28.md`.

## Slice Gates

| Slice | Task | Primary checks |
| --- | --- | --- |
| Reviewed plan | `task_40` | second critical plan review; zero conflict markers; `git diff --check`; `oc plan doctor` |
| Hermetic validation | `task_41` | fixed-clock generator fixtures; two clean selftests; Python compile |
| Model harness | `task_42` | path attack matrix; chunk flood/kill/drain tests; realistic projects smoke |
| Gateway state | `task_43` | TS/Python focused tests; real cross-runtime barrier probe; lint/build/full gateway tests |
| Shared config | `task_44` | destination writer inventory; transaction attack/concurrency matrix; representative commands |
| Devtool retirement | `task_45` | focused policy tests; no mutable installer calls; docs checks |
| Exact ast-grep | `task_46` | conditional terminal gate: ADOPTED requires local archive authority tests, isolated installer/doctor, and owner-host benchmark replay; otherwise DEFERRED leaves no adoption artifacts |
| Closure | `task_47` | complete matrix below; final critical review; remote overlap check |

## Full Closure Matrix

```bash
git diff --check origin/main...HEAD
git status --porcelain=v1 --untracked-files=all
python3 -m py_compile scripts/update_release_index.py scripts/selftest.py scripts/harness_wave2_task4_smoke.py scripts/gateway_plugin_bridge.py scripts/config_layering.py scripts/devtools_command.py
make validate
make selftest
make selftest
make install-test
npm --prefix plugin/gateway-core run lint
npm --prefix plugin/gateway-core run build
npm --prefix plugin/gateway-core test
pre-commit run --all-files
```

Also require:

- a tracked-file hash manifest before and after each full validation bundle;
- gateway lint/build/tests and workflow scenarios on Node `26.5.0` and
  `22.23.1`;
- corrected plugin-scoped npm package dry-run and package parity;
- provider-boundary secret smoke;
- if `task_46` is ADOPTED, exact ast-grep local archive/installer/doctor and
  owner-host benchmark replay; if DEFERRED, proof that no ast-grep adoption
  artifact or managed executable landed;
- direct and tuple local gateway contract probes;
- projects-only exact `openai/gpt-5.4-mini` E2E in a fresh unique output path:
  Python and Node pass, only implementation files change, test hashes remain
  unchanged, captures stay bounded/sanitized, and cleanup is confirmed;
- a tracked closure audit outside `runtime/` containing sanitized evidence hashes,
  commands, result freshness, OS/architecture, and owner-host/CI classification.

Browser/MCP E2E is not required because no browser, MCP, or hosted runtime is
adopted or enabled.

## Acceptance Gates

- No validation command writes tracked files or requires a restoration command.
- Harness rejects every existing or unauthorized output path and returns within
  one bounded deadline without surviving tracked process-group members or
  harness-owned reader threads/pipes. Deliberately detached same-UID descendants
  are outside this process-group contract.
- Cross-runtime gateway state updates preserve all sibling and unknown domains.
- Concurrent config mutations preserve updates or fail before replacement;
  multi-file partial commits are explicit; victims never change.
- Managed plugin and MCP inventories remain unchanged and external-free.
- Mutable devtool installers and unnecessary required tools are retired.
- If ADOPTED, exact ast-grep is the only new managed executable and passes
  independent integrity, install-authority, isolation, functionality, and
  cleanup gates. If DEFERRED, no new managed executable exists.
- Latest critical review reports no blocker and all local/CI checks pass.

## Explicitly Deferred

- Gateway recovery PID/start-time authority and automatic stale-lock reclamation.
- Broad redacted gateway/MCP status and support-export schemas.
- New OpenCode plugins, hosted MCPs, telemetry exporters, PTY listeners, or
  browser defaults.
- DCP, Morph, notifier, worktree, background-agent, Braintrust, WakaTime,
  gh-dash, ripgrep-all, tree-sitter CLI, and Lefthook adoption.
- Automatic ast-grep rewrites, LSP integration, non-Darwin-arm64 assets, and
  parser-authoring workflows.
- JSONC formatting preservation.

## Delivery And Cleanup

- Deliver through a reviewed PR only.
- Before merge: fetch `origin`, inspect open PR paths, and require green CI.
- Exact-model and live-download cells return `BLOCKED`, not a false pass, when
  trusted OAuth, supported platform, or network availability is missing.
  Exact-model `BLOCKED` stops closure; ast-grep `BLOCKED` forces the DEFERRED
  terminal outcome and cannot authorize adoption.
- Before deleting the worktree: replay/export the Wave 8 graph to the durable
  main store; run `oc plan doctor`; create a `0600` checksummed export outside
  the worktree; import it into an empty store; and compare entity IDs, statuses,
  dependency edges, counts, and content hashes. Any mismatch leaves the
  worktree and tmux sandbox intact.
- After merge: preserve primary-main user overrides, sync `main`, remove the
  branch/worktree/tmux sandbox, and verify no Wave 8 process or branch remains.
