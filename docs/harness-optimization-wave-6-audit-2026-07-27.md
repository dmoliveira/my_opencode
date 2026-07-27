# Harness optimization Wave 6 audit

Date: 2026-07-27

## Outcome

Wave 6 fixes four reproduced reliability and safety defects while keeping the
runtime external-free by default:

- Python-backed commands now fail before mutation on runtimes older than 3.11
  and consistently honor the selected `PYTHON` interpreter.
- Delegation terminal events fan out to every enabled consumer before one
  coordinator cleanup, preserving the first fatal error without losing later
  cleanup hooks.
- LSP request deadlines now cover writes, framing, server-request replies, and
  responses; bounded pumps prevent stderr floods and partial frames from
  hanging the caller.
- Browser work gains an optional, exact Playwright CLI path with provenance
  checks and scoped process ownership. Firecrawl is retired from managed
  defaults without deleting user-authored custom entries.

No new MCP, plugin, browser process, telemetry exporter, or external service is
enabled by default.

## Delivered slices

### Python runtime contract

`Makefile`, `install.sh`, CI, and focused tests now require Python 3.11 or
newer. Unsupported runtimes fail before installer state changes. The supported
interpreter is threaded through validation and self-test recipes instead of
falling back to a shell-local `python3`.

### Delegation terminal lifecycle

The gateway coordinator owns completed-message and child-deletion fan-out.
Known linked children dispatch every enabled consumer exactly once in either
event order, cleanup occurs once, interleaved children stay isolated, and the
first fatal hook error is rethrown after later hooks run. Idle, progress, and
unknown-child behavior remains unchanged.

### Deadline-safe LSP transport

The LSP client uses bounded stdout, stderr, and stdin pumps with one monotonic
request deadline. It caps headers, bodies, queues, and retained stderr; handles
fragmented and multiple frames; replies to server requests; distinguishes
server errors from transport errors; and terminates, reaps, closes, and joins
owned resources on failure.

### Verified browser path

`@playwright/cli@0.1.17` is optional and never part of `/devtools install all`.
Before package execution, the devtool path checks the exact version,
Apache-2.0 license, Node range, SHA-512 integrity, SHA-1 package shasum, and the
absence of lifecycle scripts. npm runs with empty user/global config files, a
fixed public registry, ignored lifecycle scripts, an owner-only versioned
cache, and no provider/token/secret environment variables.

The browser harness rechecks provenance, uses a unique session, completes a
local Todo flow, closes only its own session, revalidates process identity
before cleanup, and retains bounded relative artifacts. The disabled
`@playwright/mcp@0.0.78` path now uses the same npm isolation, rejects lifecycle
script drift before execution, bounds protocol logs, and requires exactly 68
tools.

### Firecrawl retirement

Firecrawl is no longer a bundled default, active managed server, profile, web
member, `all` member, or enable target. It remains a disable-only compatibility
target:

- absent or already-disabled named disable is byte-stable;
- existing custom command, URL, and options are preserved while only `enabled`
  changes to `false`;
- profiles and `disable all` disable an existing retired entry but never create
  one;
- `enable all` leaves a custom retired entry untouched;
- human and JSON diagnostics expose only retirement state, never its custom
  endpoint or command.

## External tooling decision

The exact Playwright CLI package passed the stop/go gate and reduced the fixed
Todo flow output from 41,397 bytes of MCP protocol/tool inventory to 664 bytes
of CLI result data in the discovery benchmark. It was adopted only as an
on-demand, exact-pinned path. Always-on hosted MCPs, global npm installs,
external skill installers, cloud memory, external tracing, DCP/Sleev, Type
Inject, and GitHub Action agents remained rejected or deferred because they did
not clear the safety, overlap, or measured-value threshold.

## Validation evidence

All implementation cells passed on committed code candidate `d947683` in tmux
session `ai-oc-harness-wave6`. Closure commit `9a66ae1` added this audit and
moved the approved plan to `done`; `make validate`, pre-commit, and diff checks
passed on that closure head. The follow-up closure correction changes only plan
status and this provenance wording, not executable surfaces:

- Python `3.14.6`: unittest discovery `93/93`, critical Ruff rules,
  `py_compile`, `make validate`, and `make selftest`.
- Apple clangd `21.0.0`: eight fake/adversarial transport cases plus required
  real-clangd lifecycle smoke, with closed streams, reaped child, and no live
  transport threads.
- Node `26.5.0` and Node `22.23.1`: gateway lint, build, and full tests
  `752/752` on each runtime.
- Workflow scenarios: `20/20` at the required 100% threshold on both Node
  runtimes.
- Playwright CLI Todo gate: exact provenance and version, open/fill/click/
  snapshot/screenshot/scoped-close exits `0`, visible `1 items` and
  `Ship Wave 6`, sandbox-only writes, and zero surviving or unverified owned
  processes.
- Playwright MCP gate: pinned provenance, no lifecycle scripts, protocol
  `2025-11-25`, and exact inventory `68/68`.
- Firecrawl retirement: focused tests `8/8`, including byte-stable absent state,
  custom-field preservation, profile/all semantics, and output redaction.
- Exact-model E2E: `openai/gpt-5.4-mini` completed Python and Node fixtures,
  changed only `stats.py` and `slugify.mjs`, retained original test hashes,
  observed one configured model, used no project shim, and cleaned its sandbox.
- Package/install: clean gateway rebuild, npm dry-run, extracted package parity
  for one config file, 260 dist files, and routing data, plus committed-clone
  `make install-test`.
- Security/pre-PR: provider-boundary secret smoke, sanitized evidence checks,
  `pre-commit run --all-files`, `git diff --check`, and a clean tracked tree.

Machine-readable evidence is retained under `runtime/harness-wave-6/`, including
`final/`, `exact-model-e2e/`, `playwright-cli/`, `playwright-mcp/`, `lsp/`,
`delegation/`, and `firecrawl/`.

## Review record

The high-risk budget was met with architecture and plan-critic approval,
per-slice independent verifiers, blocker-first LSP review, and a critical
browser/security review. The browser review initially blocked on MCP npm
isolation, unbounded MCP logs, and PID-reuse cleanup risk. Those findings were
fixed, the affected live gates were rerun, and the same reviewer returned PASS
with no new blocker.

## Residual risks

- Credential-backed exact-model proof depends on the trusted host OAuth store
  and provider availability; CI intentionally does not run this cell.
- Standard CLI guidance uses an exact package version after the devtool
  provenance gate. The executable harness revalidates metadata on every run,
  while ordinary ad hoc CLI commands still depend on npm cache/registry
  integrity for that exact version.
- Process identity uses PID, start time, and command. Ambiguous or changed
  identity fails cleanup safely instead of signaling an unverified process.
- Existing custom Firecrawl entries are preserved rather than deleted. Managed
  profiles disable them, but an external editor can still re-enable one.
- LSP pump threads are daemonized as a final interpreter-exit safeguard; normal
  and tested failure paths explicitly join them.

## Rollback

Revert `d947683`, `44fbfac`, `cf89f87`, `9b3cd15`, and `8d07bb0` in reverse
delivery order, then rebuild `plugin/gateway-core/dist/**`. The planning commit
`d60ecec` and this closure document can be reverted independently. Reverting
Firecrawl retirement does not recover deleted user data because the migration
never deletes custom entries.
