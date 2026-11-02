# Audit-bound locked Python setup

The enabled dependency-risk guard now has a **narrow authorization path**, not a general package-manager allowlist. Unsupported operations remain blocked. A vulnerability audit reports known findings; it is not proof of package safety or a replacement for code review.

## Supported project

- POSIX host, UV **0.13.6**, and an already installed exact Python **3.11–3.14 patch version** declared by `.python-version`; no interpreter downloads.
- One canonical Git worktree, regular non-symlink/non-hardlinked project inputs, `pyproject.toml` and `uv.lock`.
- An explicit **virtual application**: `[tool.uv] package = false`, no build system/dynamic metadata, registry-only hashed wheel dependencies, default development group only. No project wheel/editable build or installed project console entrypoint is claimed.
- A fresh environment: `.venv` must not exist. The guard never silently deletes or overwrites an existing environment. Preserve any delivery-owned partial environment separately before requesting a fresh setup.
- An existing, fixed **pip-audit 2.10.1** security-tool environment in UV's cache for that interpreter. Audit execution discovers it through the pinned offline tool workflow and hashes its actual code; it cannot substitute a project-provided auditor. Missing tooling fails closed rather than creating project dependencies or bypassing setup controls.

The initially selected host-managed Git, Node, UV, Python and cached auditor must already be trusted. Hash binding establishes continuity, not initial authenticity or supply-chain provenance. Bootstrap hashes tools before discovery calls; subsequent verification is filesystem-only and never executes changed tools to discover their identity.

Other package managers, project build backends, direct/VCS/local dependency sources, custom UV configuration, group/extra selections and installer variants are not supported by this authorization. They require a separate reviewed extension; do not hide them in scripts, Make recipes or another installer.

## Native OpenCode sequence

Start OpenCode **rooted in the actual canonical worktree**, not merely a shell `cd`/tool `workdir`. Run these as separate native Bash calls in the same session, with no aliases, shell chaining, environment overrides, redirects or extra flags:

```text
dependency-security authorize-uv-sync-locked
uv sync --locked
```

The first command is a runtime request, not an executable to install on PATH. The guard rewrites it to its verified audit runner. It exports the actual lock, evaluates host markers with the pinned auditing environment, proves wheel/version/hash coverage and runs the real strict audit. A matching successful runtime-observed call grants short-lived, single-use authority in memory.

The second exact command consumes that authority **before** execution. A private one-shot host handshake permits only its trusted setup runner; the runner verifies a strict retained snapshot and hashes the granted auditor without executing or rediscovering it, rejects changed identities before tool/scanner execution, repeats the real audit, installs the complete hashed wheel closure without source builds, runs the locked virtual-project sync and verifies installed external package-set equality. Every subprocess shares that non-executing preflight. The fresh environment's directory identity is bound before package operations. No installation occurs in the before-hook, and direct helper invocation is not a supported authorization route.

Do not insert unrelated Bash commands between the two requests. Failure, expiry, compaction/deletion, restart, replay, changed worktree/input/interpreter/auditor/runner or nonnumeric/nonzero/malformed results invalidate authority. No manual JSON, printed PASS, caller flag or edited ledger file grants permission. A failed setup may leave a partial environment; it is never claimed ready, and a retry needs a new audit and fresh supported environment.

Safe metadata/build forms use exact bare package-manager names, not arbitrary absolute paths or aliases. Explicit configured command denials still apply. The runtime verifies rewritten authorization/setup commands after every before-hook, including evidence recording.

The mandatory shell hook adds the actual session identity internally. The dependency guard recognizes and preserves only that exact session prefix; this does not authorize caller-selected environment overrides, wrong sessions or duplicate assignments.

The runner receives bounded canonical snapshot evidence containing executable/helper hashes, project input hashes, directory identities and the Git marker binding. That serialized evidence is not authority: exact host call correlation and the live one-shot capability are still required for setup.

## Privacy and deployment

### Patch target classification

The patch guard checks native Add/Update/Delete operation paths and both rename
endpoints. Protected filenames appearing only inside source, test or documentation
hunks are not file operations. Raw and normalized endpoint checks remain
conservative; malformed/ambiguous patches, quoted/control-character targets and
patches exceeding 4 MiB of UTF-8 bytes fail closed. This is lexical target
classification, not filesystem alias/symlink hardening. It grants neither lock
editing permission nor installation authority.

Audit events contain reason codes, not project names, dependency inventories or credentials. Runner failures are redacted; local/private evidence is not copied into public change descriptions. This is an instrumented command guard, not an OS sandbox for arbitrary malicious programs; ordinary tool permissions and project-scope rules still apply.

Privileged concurrent replacement between the last static check and OS process creation is outside this guard's threat model. Use OS isolation when hostile concurrent processes are in scope; do not interpret hash continuity as an execution sandbox.

Source and tracked generated `dist` must be built/reviewed together. Configuration and plugins are loaded at startup: **quit/restart existing OpenCode processes** to use the change. Before real setup, a fresh rooted runtime must confirm reviewed runner/guard hashes, enabled enforcement and denial of an unsupported request. Existing processes retain the old behavior; do not disable hooks or edit authorization state to force activation.

## Validation evidence

The scoped implementation is tested with adversarial session/call/nonce/command/hash/expiry/replay, path/link, malformed output, closure/marker, auditor, mutation, capability and unsupported-operation fixtures. The explicit audit-only smoke script never performs setup:

```sh
npm --prefix plugin/gateway-core run build
npm --prefix plugin/gateway-core run lint
node --test plugin/gateway-core/test/dependency-authorization.test.mjs plugin/gateway-core/test/dependency-risk-guard-hook.test.mjs
node plugin/gateway-core/test/dependency-authorization-audit-smoke.mjs
```

The smoke requires real registry access and the existing scanner cache; unit tests use synthetic boundaries. Full gateway tests and repository checks remain required before delivery. Do not represent unavailable checks, an unrelated baseline failure, or source-only tests as successful activation.

### Raw result dispatch boundary

For native `tool.execute.after`, the selected dependency receiver runs exactly
once before the validation-evidence ledger and presentation hooks. The remaining
hooks retain their relative order. This is an AFTER-only boundary; global hook
priorities, BEFORE dispatch and final command binding are unchanged. Watchdog
notices remain visible, but are appended only after strict receipt verification.
Producer output must still be exactly the canonical frame: producer chatter,
footers, duplicate fields/frames, trailing bytes and malformed JSON are rejected.
Later presentation cannot turn rejected output into authorization.

Every failed AFTER dispatch result sends an awaited internal
`tool.execute.after.error` cancellation to that selected dependency receiver only.
It clears the actual session's audit/metadata state and pending capabilities.
Missing identity cannot clear other sessions. Critical/blocked errors still
surface the original error; tolerated failures still continue, after revocation.
No receipt is persisted and there is no caller-selected raw-output field or
authorization flag.

Rebuild before running the focused dispatch proof:

```sh
npm --prefix plugin/gateway-core run build
npm --prefix plugin/gateway-core run lint
node --test plugin/gateway-core/test/raw-result-dispatch.test.mjs
```

The portable test uses test-process-only resolver doubles with the real guard,
ledgers, continuity checks, sockets, full plugin and watchdog. It covers audit
and metadata authority, critical/blocked/tolerated/ledger failures, cleanup timing,
pending socket removal, session isolation, one-use permission and strict parsing.
It never executes setup or requires installed resolver/scanner tooling.

The opt-in `test/dependency-metadata-promotion-smoke.mjs` requires the documented
enforced sidecar and installed pinned tools. Its explicit hook selection includes
the watchdog. Empty synthetic read completions prime the unchanged configured
call threshold; the actual CHECK result must acquire a visible watchdog footer
and still authorize exactly one synthetic metadata promotion. Separate probes
append chatter to actual producer output and require rejection. Only owned
synthetic inputs are changed; no installer runs. Child counts are observed;
checker command counts are labelled as expectations or upper bounds.

This scoped proof does not replace full clean checks, independent review/CI or a
fresh enabled linked-host watchdog proof before resuming private consumers.

## Phase A: read-only editable-root feasibility

`captureMetadata` uses the named informational policy
`read-only-editable-dot-metadata-v1`. It accepts exactly one static editable-dot
root whose name/version match the manifest, with explicit `package = false`, no
backend/dynamic metadata, and the existing registry/wheel restrictions. Its
conservative manifest subset excludes URL dependencies, extras/groups beyond the
supported default, custom tool configuration and workspaces. Ordinary `capture`
still requires a virtual root. Metadata snapshots are explicitly rejected by
normal audit/setup entry, scanner discovery/capture and runner command creation;
they cannot issue an audit frame or installation permission.

`checkMetadata` reads hash-bound frozen inputs and accepts only one canonical
`source = { editable = "." }` line (optional trailing comment). It changes exactly
the eight UTF-8 bytes `editable` to the seven bytes `virtual`; prefix/suffix bytes
are retained exactly. The bound interpreter's isolated standard-library
`tomllib` strictly parses both versions, rejects duplicate keys, and proves that
the entire parsed document differs only in that root source. Every external
record, edge, hash, top-level field, comment and other byte is preserved. Other
formatting fails closed rather than invoking a TOML rewrite or regeneration.

The checker resolves and validates the existing temporary parent before creating
staging. A parent equal to or beneath the source root is rejected, with no
fallback. It walks that parent and every ancestor through filesystem root and
rejects any `pyproject.toml`, `uv.toml` or `.python-version` entry, regardless of
file type (including dangling symlinks). It stages only frozen manifest, pin and
candidate in a private directory, binding both parent and staging directory
identities. Each parser, version and consistency subprocess first rechecks this
ancestry/isolation boundary, the bound snapshot, staged bytes and supplied
original/environment sentinel hashes. `--no-config`, explicit cwd/project and
an arbitrary Git marker alone do not establish workspace isolation.
The same checks run after completion or failure, and staging is removed. Its only
resolver operation is:

```text
uv lock --check --offline --no-config --no-cache --no-build --no-python-downloads --python <bound-installed-interpreter> --project <private-stage>
```

UV must identify as **0.13.6**, and the installed interpreter must match the exact
pin. `--no-cache` documents independence from existing dependency metadata cache;
it does not remove the host cache or installed interpreter. Temporary/cache
environment paths are confined to owned staging. Offline, no-build and
no-interpreter-download guarantees here are documented tool semantics, not
process/network tracing. A successful check proves consistency/freshness, not a
vulnerability audit, artifact validity, or absence of internal resolution work.
If it fails, no regeneration, upgrade, installation or promotion is attempted.

Focused units use synthetic subprocess boundaries plus isolated Python 3.12
stdlib parsing; they require neither a resolver nor network. The explicit opt-in
smoke uses the same checker with installed pinned tools:

```sh
node --test plugin/gateway-core/test/dependency-metadata.test.mjs
node plugin/gateway-core/test/dependency-metadata-smoke.mjs
```

The smoke creates only its own synthetic metadata, Git marker, environment
sentinel and sibling staging parent, restoring temporary-directory environment
variables afterward. Bootstrap performs read-only Git/tool/interpreter discovery. Its frozen
external wheel URL/hash are deliberately synthetic: no artifact is fetched or
verified. The observed UV 0.13.6 / Python 3.12.16 run accepted the single-key
conversion with an external record and root dependency/metadata edges unchanged;
original-input and sentinel hashes remained identical. It prints bound tool
identities, exact checker arguments, checked staging isolation/cleanup, span and before/candidate hashes. No network
or process trace was collected. This narrowly establishes metadata feasibility;
it grants no live-project write authority. The separate Phase B wrapper and
promotion transition below do not expand the shared Snapshot schema.

## Phase B: one-use metadata-only promotion

The runtime source supports a separate check-to-migrate sequence for the same
already-virtual, static/no-build manifest and exactly one old editable-dot lock
root. This writer's validation is synthetic-only. Live application use remains
gated on the parent workflow's clean-process checks, independent security/oracle
review, normal delivery, reviewed artifact identity and fresh enabled native
synthetic proof. Restart OpenCode after reviewed plugin deployment; existing
processes retain their loaded code/configuration.

The exact native Bash requests, in separate calls in the actual rooted session,
are:

```text
dependency-security check-uv-lock-virtual
dependency-security migrate-uv-lock-virtual
```

Only the mandatory actual-session prefix is preserved. Flags, paths, aliases,
overrides, printed receipts and direct helpers cannot grant permission. Existing
environments are preserved/ignored by these two metadata operations only. Neither
operation audits vulnerabilities, verifies artifacts, regenerates a lock or
authorizes installation. Normal audited setup still requires a fresh environment.

### Context, frames and state

The bounded canonical `one-key-metadata-promotion-v1` wrapper binds the unchanged
read-only-policy Snapshot plus the original lock's canonical path, SHA-256,
device/inode, UID, size and mode; canonical Git-common directory identity; and
either absence or exact safe `commondir` pointer identity/bytes/target relationship.
Pointers resolve relative to the Git directory, removing only one final LF.
Trailing spaces are path bytes; embedded controls are rejected. Files must be
regular, single-link, current-owner, owner-writable, non-executable and without
special bits or group/world writes. Unsupported permissions fail rather than
being repaired.

The dedicated in-memory MetadataLedger has check-pending, one-use metadata-permit
and migrate-pending transitions. Pending checks expire after 180 seconds; permits
and live migration capabilities expire after 60 seconds. The ledger and native
reservation bind phase, actual session/call, migration issuer call, root, context
fingerprint, original/candidate hashes, nonce and exact final rewritten command.
The final guard runs after ordinary before-hooks. Migration consumes authority
synchronously before its first await; conflicting in-flight requests cancel and
fail closed. Restart, expiry, cancellation, compaction/deletion, replay and
unrelated Bash clear authority. Every metadata request revokes installation
authority, including rejections; normal audit/setup requests revoke metadata
authority, including rejections.

Results are one canonical minimal frame containing only `v, phase, session, call,
issuer, root, fingerprint, nonce, original, candidate`, in that order. Unknown or
duplicate keys, extra output, wrong correlation and nonnumeric/nonzero exit codes
fail closed. Raw checker reports, TOML, argv and inventories are not printed. The
metadata grammar never enters the audit-success parser or issues an install permit.

### Preparation, atomic replacement and recovery

Migration independently repeats the accepted checker and requires its exact
candidate hash. Before redeeming its domain-separated private host capability it
creates these deterministic, nonce-bound paths:

- `<canonical-Git-common>/dependency-metadata-backups/<nonce>/original.lock`:
  exclusive original-byte backup, mode 0600, inside current-owner 0700 namespace
  and exclusive job directories. Linked worktrees use common metadata, not their
  disposable worktree Git directory. Collisions are never overwritten/reused.
- `<source-root>/.dependency-metadata-<nonce>.candidate`: exclusive candidate on
  the source filesystem, preserving the supported original mode/owner.

Both helper and live final-checked host callback independently verify the paths,
parent identities, ownership, permissions, original/candidate hashes and prepared
file identities. Both retain descriptors so inode reuse cannot masquerade as the
prepared candidate. After redemption the helper performs only pure filesystem,
source/pointer/common/tool continuity checks, then atomically renames that candidate
onto the predetermined lock path. There is **no subprocess after redemption**.
Native completion independently requires that exact prepared inode/device,
candidate size/hash, owner/mode and single-link status at the original target, with
all non-lock bindings unchanged. Identical-byte unrelated replacements fail.

The guarantee covers atomic replacement and private recovery evidence across
**process failure**, not power-loss durability. Completed original backups are
retained; incomplete job directories are also retained and must never be treated
as verified originals or reused. Before rename, cleanup removes only the owned
identity-matched temporary candidate. It never removes a replacement or backup
history. After rename, there is no source cleanup, rollback or automatic audit/setup.
Missing/malformed completion, verification failure or cancellation racing after
redemption can be **indeterminate**. Do not infer “no write,” assume success, or
retry over promoted/newer work. Inspect the predetermined source and retained
private recovery evidence independently; runtime failures expose no raw report.

### Synthetic validation

The default adversarial tests require no resolver or network. Runner fault
injection is an explicitly synthetic in-process boundary unavailable to the CLI.
The opt-in proof creates only fresh random temporary Git fixtures, exercises the
production checker/runner and full plugin with enforcement enabled, and uses
asynchronous children so the host capability server can respond. It covers normal
and linked Git metadata, existing/absent environment sentinels, native correlation,
final-gate/cancellation failures and lost completion. Setup denial is asserted
before execution; no installer is launched, even as a negative test.

```sh
npm --prefix plugin/gateway-core run build
npm --prefix plugin/gateway-core run lint
node --test plugin/gateway-core/test/dependency-metadata-authority.test.mjs plugin/gateway-core/test/dependency-metadata.test.mjs plugin/gateway-core/test/dependency-authorization.test.mjs plugin/gateway-core/test/dependency-risk-guard-hook.test.mjs
node plugin/gateway-core/test/dependency-metadata-promotion-smoke.mjs
```

The opt-in promotion smoke requires `MY_OPENCODE_GATEWAY_CONFIG_PATH` to select
the documented `enforced-config.json` sidecar, with `hooks.enabled: true`,
`hooks.disabled: []` and `dependencyRiskGuard.enabled: true`. It verifies those
values and preserves tracked/user settings. Its three checker subprocesses per
native child are isolated Python parsing, UV version and offline lock check;
bootstrap Git/tool discovery is separate. Temporary fixtures are removed only
after backup/source/environment assertions; the smoke restores its temporary
directory environment variables. These tests are evidence for parent review,
not authorization for live application work.
