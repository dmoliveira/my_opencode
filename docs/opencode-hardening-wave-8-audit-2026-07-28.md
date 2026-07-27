# OpenCode hardening Wave 8 audit

Date: 2026-07-28

## Outcome

Wave 8 closes five runtime and validation risks, retires unnecessary mutable
tooling, and adopts one narrowly managed executable:

- documentation generators validate against disposable fixtures and leave the
  tracked repository unchanged;
- exact-model harness output is path-authorized, bounded, sanitized, and cleaned
  without recursive ownership guesses;
- gateway state and shared configuration writes use lock-coordinated,
  compare-and-swap transactions with explicit partial-commit reporting;
- mutable Homebrew and GitHub-extension automation is removed from `/devtools`;
- Darwin arm64 may install exact `ast-grep 0.45.0` after archive, binary,
  execution, publication, recovery, and doctor authority checks.

No plugin, MCP, hosted service, telemetry exporter, unattended updater, or
automatic ast-grep rewrite is enabled. Deprecated `sg` is not installed.

## Delivered slices

### Hermetic validation and model harness

Release-index and docs-summary fixtures use explicit roots and fixed timestamps.
Repeated selftests produce identical tracked bytes. The model harness accepts
only a fresh output directory under repository `runtime/`, creates an ownership
marker, bounds process groups and captured streams, and rejects existing,
outside, or unsafe paths without changing victims.

### Durable gateway and shared configuration state

Gateway TypeScript and Python state writers share a private lock protocol,
validate plan-time and commit-time identities, and preserve sibling and unknown
domains. Shared configuration changes use stable descriptor-anchored locks,
alias-safe provisioning, retained staging descriptors, and compare-and-swap
publication. Retained descriptors prevent swapped stage names from becoming
cleanup victims even under immediate inode reuse. Multi-file failures report
exactly which destinations committed instead of claiming rollback.

### Developer-tool policy

`gh-dash`, `ripgrep-all`, `tree-sitter-cli`, and Lefthook are no longer managed
or recommended. Other host tools remain observation/manual-only. Playwright CLI
stays exact, explicit, and outside `install all`; hook setup invokes only the
resolved local `pre-commit` executable with a finite deadline.

On Darwin arm64, `/devtools install ast-grep` and `install all` may manage the
pinned Apple Silicon `ast-grep 0.45.0` binary in pre-existing owner-only roots.
The installer uses a scrubbed stdlib-only downloader child, exact two-entry ZIP
profile, bounded staged execution, native `renameatx_np(..., RENAME_EXCL)`,
transaction-attributed attestation, crash finalization, offline idempotence, and
a read-only doctor that rehashes the binary on every call.

## Validation evidence

The authoritative owner-host run executed from committed candidate
`8cb7aeb220b1f13d585767bbd58bb88bc7835c42` against
`origin/main` `f1a529732a16567b813c1939a89041d37832a870` in tmux session
`ai-oc-hardening-wave8`. The host was Darwin arm64 `25.4.0`, Python `3.14.6`.
The run completed at `2026-07-27T22:12:32Z` (`2026-07-28` local time).

The full closure matrix passed:

- `make validate`: `213` tests passed with one expected opt-in live-cell skip;
- two consecutive `make selftest` runs, `make install-test`, and
  `pre-commit run --all-files` passed;
- gateway lint, build, and all `783/783` tests passed on Node `26.5.0` and
  Node `22.23.1`;
- workflow scenarios passed `20/20` at the 100% threshold on both runtimes;
- `npm pack ./plugin/gateway-core --dry-run --json` and an actual
  `--ignore-scripts` package proved source-byte parity for all `265` files under
  `config`, `dist`, `package.json`, and `routing-profiles.data.json`;
- provider-boundary secret smoke retained no canary or host credential and
  produced only safe audit evidence;
- direct and configured-tuple gateway contracts both passed and cleaned their
  artifacts;
- a read-only Python `3.11` Linux arm64 container passed `62` focused ast-grep,
  `/devtools`, and shared-configuration transaction tests with the expected
  Darwin-only live-cell skip;
- the sandbox-confined ast-grep owner-host cell observed the exact release URL,
  redirects, archive profile, hashes, child environment and descriptors, native
  no-clobber publication, successful doctor rehash, zero survivors, a
  network-denied write-free second install, expected fixture behavior, and
  cleanup;
- exact `openai/gpt-5.4-mini` preflight, Python, and Node projects passed with
  OAuth-store-only authentication and zero forwarded API keys. Only `stats.py`
  and `slugify.mjs` changed, test hashes stayed unchanged, captures stayed
  bounded, retained artifacts scanned safe, and aggregate cleanup was confirmed.

Every core, Node 26, Node 22, integration, and exact-model bundle recorded the
same tracked-file manifest SHA-256
`29d1a84e4ba4e4347165ade6afbb7a4314e9f219a6ff807410db819d320196eb`
before and after execution; status and diff artifacts were empty. No validation
command required tracked-file restoration.

Sanitized machine-readable evidence is ignored under
`runtime/harness-wave-8/task47/run-a62e68e0e8db4673bcf8a1eb99bf7976/`.
Important evidence hashes:

| Evidence | SHA-256 | Classification |
| --- | --- | --- |
| Closure summary | `88a0787f7f3359991b60b132d3eb6f9c6a5ef3d4510cf35c1054c5b6372592ad` | owner-host aggregate |
| Exact-model report | `73c0957da46304e2b479227cfce6ab56c1a487c94e81a0701191bec03830efbc` | credential-backed owner-host |
| ast-grep owner-host report | `a96dcb165d2ad9421a74a1905153e159c404a85b4dd9f026c82a6586034b2ead` | networked Darwin-arm64 owner-host |
| Package parity report | `33ad44aaf281e640c3ef5bca9b4d229b426ec2cf45a44e0d105098c0dc32e15f` | CI-reproducible |
| Provider secret-smoke report | `24c702b7e8f2b0748314722725fc4b26f6504b96f211e876158a7e991c8fd2ab` | local-runtime owner-host |
| Direct/tuple contract report | `e101283c35362d2cebc5698d94a5f14c0b20f511b4106ad0c49c88a754d0da33` | local-runtime owner-host |
| Python 3.11 Linux focused log | `868c2bb14ee5c3f0839da98fb72e585a4eee4c11552fa897221bf635bcc9449c` | container-reproducible |
| Executed command log | `e6e5dcf10c22527dfea8dbc797324898a392d71151ae418ed4790a6749bdbeb3` | sanitized owner-host |

Core tests, dual-Node tests, scenarios, package parity, and static checks are
CI-reproducible. The Python 3.11 Linux container additionally exercises the
portable staging and victim-safety regressions. The exact-model OAuth cell,
live ast-grep download, and local OpenCode runtime probes remain owner-host
gates.

The first closure-wrapper run parsed the contract report as if it had a
top-level `result`; the report correctly stores separate direct and tuple
results. The assertion was corrected, and the entire matrix was rerun from the
beginning. The authoritative run above passed without reusing the failed run's
state.

Hosted CI then exposed two Linux-specific assumptions that the first owner-host
run could not reproduce: executing a staged binary while its write descriptor
remained open (`ETXTBSY`), and immediate inode-number reuse after a malicious
stage-name swap. The installer now retains only a read descriptor before
execution and treats zombie-only process groups as reaped after direct-child
collection. Shared configuration transactions retain each stage descriptor
through replacement and cleanup, so pathname reuse cannot transfer ownership.
Both fixes have direct regressions. Final GitHub Actions run `30309232927`
passed the Python-minimum and full validation jobs at candidate `8cb7aeb`.

## Review record

The high-risk review budget included reviewed architecture plans, independent
slice verification, oracle recovery/security analysis, and repeated critical
implementation reviews. Findings tightened root and destination authority,
transaction attribution, directory durability, process-group teardown,
descriptor cleanup, managed-doctor semantics, and measured owner-host evidence.
The latest implementation and operator-guidance reviews reported no blocker,
hosted CI was green, and the full matrix passed on that committed candidate.

## Residual risks

- The ast-grep release has exact archive and binary pins but no vendor signature
  or reproducible-build proof connecting the binary to source. The managed path
  therefore remains Darwin arm64 only and fails closed elsewhere.
- Credential-backed exact-model proof depends on the trusted owner-host OAuth
  store and provider availability, so CI cannot reproduce that cell.
- Active malicious same-UID mutation is outside the ast-grep installer threat
  boundary. Exclusive publication still prevents accidental or cooperating
  destination replacement.
- Gateway recovery PID/start-time authority, automatic stale-lock reclamation,
  broad redacted support exports, and JSONC formatting preservation remain
  deferred.

## Rollback

Revert `8cb7aeb`, `26f1184`, `feabc6f`, `f6dd93a`, `b8692f5`, `682964d`,
`f74a437`, and `86dd087` in reverse delivery order. Rebuild
`plugin/gateway-core/dist/**` after reverting gateway source. The planning
commit `37ebcfd` and closure-audit commits can be reverted independently.
Rollback must not overwrite primary-main user configuration or treat an
unattested executable as managed.
