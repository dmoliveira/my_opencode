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
