# Native V2 dependency-boundary observations

Status: diagnostic contract, **not authorization**. No dependency installation
authority is enabled or qualified by this probe, including when it reports PASS.
The legacy dependency workflow remains Python/uv-only and is not activated here.

## Reproduce

With the already installed OpenCode **2.2.5** and Python 3.11+:

```sh
make gateway-v2-dependency-probe PYTHON=python3.12
```

The Make target invokes Python directly. It does not build the gateway, run a
package manager, install an SDK, or modify user configuration. A different host
version fails measurement rather than inheriting these observations. The
script's stdout is one JSON report; Make also prints its usual command/runtime
lines. Run the Python script directly when machine-readable stdout is needed.

## What is measured

The actual native `shell` tool is inspected, never replaced or wrapped. Its
parameter schema is captured from the localhost provider request, with
descriptions omitted and the original schema hashed. A tool transform records
definition keys/types without changing it. An observer plugin records native
BEFORE identity, session-directory lookup, shell-create input and AFTER result
shape/numeric exit candidates. A second plugin deliberately runs later.

Five separate fresh runtime fixtures exercise:

| Case | Fixed command and observation |
| --- | --- |
| Baseline | `printf` writes an owned witness and stdout. |
| Nonzero | `printf` writes an owned witness, then `false` returns nonzero. |
| Late tool mutation | Later BEFORE hook substitutes a different fixed `printf`. |
| Late shell mutation | Later shell-create hook substitutes a different fixed `printf`. |
| Late AFTER error | Later AFTER hook throws after an earlier observer saw completion. |

The trace records each callback, not an invented raw executor envelope. AFTER
identity is reported only when that event actually contains it; it is never
filled from a prior BEFORE event. Numeric fields are candidates, not proof of an
authoritative raw-before-presentation result. A single observation does not
prove an exactly-once host guarantee.

## Observed on 2.2.5

The five synthetic cases collected on 2026-11-03 exposed this native schema:
required `command: string`; optional `workdir: string`, `timeout: integer` and
`background: boolean`. The inspected native definition had a function-valued
executor; the probe did not call or wrap it directly.

BEFORE and AFTER events both exposed `sessionID`, `messageID`, `id`, `agent` and
`tool`. The session lookup matched the fixture directory. Shell-create events
exposed `command`, `cwd`, `timeout`, `shell` and `env`, but no session/call identity
in the observed keys. No missing correlation was manufactured from that event.

| Case | Collected observation |
| --- | --- |
| Baseline | Owned baseline witness; numeric `result.metadata.exit` and `result.output.exit` were both 0. |
| Nonzero | Owned nonzero witness; both numeric exit candidates were 1, although the tool hook status was `completed`. |
| Late tool mutation | Earlier BEFORE saw baseline; later BEFORE changed it; shell-create and the witness reflected the changed command. |
| Late shell mutation | Earlier BEFORE and shell observer saw baseline; the later shell hook changed the command; the changed witness was written. |
| Late AFTER error | Earlier AFTER observed completion/exit 0, then the late hook threw. No second error callback to the earlier AFTER observer appeared in this trace. The final synthetic consumer received the late-error marker rather than baseline output; no typed error class was captured. |

These are measured ordering gaps in the tested hooks, not a claim that every
possible V2 authority bridge is impossible. An early BEFORE check was not a
terminal binding point in these cases. Observed numeric exits and matching IDs
do not supply the missing raw-order, exactly-once or revocation guarantees.

Independent verification collected all five cases with two localhost provider
requests each and matching native BEFORE/AFTER identities. Each case's explicit
database and runtime persistence stayed within its owned fixture; all six roots
(including the version check) were removed. Real configuration file bytes and
inodes matched before/after. These checks do not prove continuous absence of
transient writes or correlate a native database session row.

## Isolation and failure rules

- Fresh private HOME, XDG config/cache/data/state, explicit database and temporary
  paths belong to each fixture. The test child receives a fixed environment
  allowlist, not host credentials, service/session overrides, proxy/loader
  variables or the user's PATH.
- Preflight rejects ancestor configuration/extension directories and existing
  system/managed configuration locations. It never disables or overwrites policy
  to make a test work. Run only on a host where that preflight passes.
- Only local plugin directories and the host-supplied SDK/provider runtime are
  used. Installer tripwires shadow package managers on the fixture PATH; a trip
  fails measurement. This is **not an OS sandbox**, network firewall, or proof
  against arbitrary absolute executables.
- The provider is a bounded synthetic localhost server, not an external/paid
  model. Its sole tool call is the real native shell; no custom shell service or
  undocumented executor wrapper substitutes for it.
- Fixture permissions deny other actions and allow only `printf`/`false` shell
  resources. A fixture safety hook also checks the exact fixed command, owned
  working directory and `/bin/sh`. No `--auto` is used. These test-only rules
  are not a production dependency guard.
- Caps: 60 seconds per runtime, 128 KiB per stdout/stderr stream, 1 MiB per
  provider request, eight requests per case, 64 trace rows and 64 KiB per trace.
  Socket reads time out. Owned process groups are terminated and reaped; cleanup
  verifies the temporary root's device/inode before removing it. Unexpected
  replacement state is preserved, not deleted.
- Reports omit prompts, request bodies, environment values and raw native
  diagnostics. They are observations, not capability tokens or receipt frames.

PASS requires collection of every case's native definition/schema, fixture
setup, BEFORE identity/directory, shell callback, expected witness, AFTER result
and provider continuation. Missing collection, wrong host, unexpected requests,
implicit installers, bounds violations or failed cleanup fail measurement.
An observed absent result field or an observed ordering gap can PASS
**measurement only**. Authority remains `disabled-unqualified` on every outcome.

## Required before any authority bridge

These guarantees are not established by this slice:

1. An immutable terminal command/directory/executable/environment binding after
   every transform and before process creation.
2. Authoritative numeric raw exit and output, observed once before presentation
   hooks, with native session/call correlation.
3. Synchronous revocation after every later failure or cancellation, including
   BEFORE/executor/AFTER exceptions and background/parallel/replayed calls.
4. Revocation across turns, compaction, session deletion, unload, reload and
   previously captured executable snapshots.

Do not promote a hook registration or a successful synthetic command into one
of these guarantees. A separately reviewed upstream boundary or authority
bridge is required before a separately reviewed frontend manager contract.

## Documentation basis

Official V2 documentation is rolling, not pinned 2.2.5 implementation evidence:
[plugin loading](https://opencode.ai/v2/docs/build/plugins),
[server hooks and snapshots](https://opencode.ai/v2/docs/build/plugins/server),
[configuration discovery](https://opencode.ai/v2/docs/config), and
[permissions](https://opencode.ai/v2/docs/permissions).
See the [migration inventory](../plan/doing/opencode-v2-migration.md) and the
[existing dependency workflow](../dependency-security-workflow.md) for the
separate compatibility and authority gates.
