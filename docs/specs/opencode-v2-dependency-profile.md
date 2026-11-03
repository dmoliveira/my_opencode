# Isolated native V2 dependency-profile qualification

Status: denial-only diagnostic, **not dependency authority**. Production ledgers,
runners, receipts and capability sockets are absent from this fixture. No result
authorizes package operations or enables the gateway in the parent session.

## Reproduce

Use an already installed OpenCode **2.2.5** and Python 3.11+:

```sh
make gateway-v2-dependency-profile-probe PYTHON=python3.12
```

This target calls Python directly: no build, SDK install or package manager.
Direct script execution emits one JSON report. Repeated `--case <name>` flags
can select debug cases; a proper subset or a selection other than the full
canonical case order leaves overall measurement incomplete and profile
UNQUALIFIED. Do not use the combined experimental adapter smoke target as a
substitute.

## Contract and outcomes

The [earlier native-boundary probe](opencode-v2-dependency-boundary-contract.md)
measured mutable later hooks and a late-AFTER notification gap. Existing legacy
protection demonstrates an owned dispatcher, not arbitrary later external-plugin
protection. This probe tests whether an isolated owned synthetic profile can
enforce selected boundaries. It does not change the legacy Python/uv-only policy.

| Outcome | Measurement | Profile qualification |
| --- | --- | --- |
| Every required observation collected, including a counterexample | PASS | UNQUALIFIED if any target witness fails |
| Unsupported required mechanism, missing collection, timeout or failed cleanup | FAIL | UNQUALIFIED |
| All 18 required cases and defined controls pass | PASS | QUALIFIED for the measured synthetic child boundaries only |

`authority` is always `disabled-unqualified`. QUALIFIED is not production admission
or a capability. Expected pre-dispatch refusal has loader/owned-server evidence
and zero model/tool dispatch; native call IDs are absent by design in those
cases. No skip/N/A can satisfy a required mechanism. The unrestricted rogue
negative control is never an approved profile.

## Required matrix

| Case | Required witness/control |
| --- | --- |
| `baseline` | Genuine native builtin shell, allowed fixed `printf`, numeric raw exit 0 before owned presentation and correlated terminal history. |
| `rogue-blocked` | Native policy prevents the owned rogue plugin from loading; no tool dispatch. |
| `rogue-unrestricted-control` | The same rogue fixture really loads without that policy; still no tool dispatch. |
| `owned-missing`, `owned-failed` | Missing/failed owned plugin refuses admission rather than silently proceeding. |
| `topology-change` | Owned configuration reload exposes cleanup and unexpected-plugin refusal before tool admission. |
| `permission-after-shell` | Native permission evaluation sees the transformed fixed command and genuine session/call source, then denies its witness. |
| `bind-cwd`, `bind-executable`, `bind-env` | Separate fixed mutations are observed and rejected by the owned chain. Command matching alone is not field attestation. |
| `after-critical`, `after-tolerated`, `after-rejection` | Actual raw result precedes owned failure; targeted synthetic state is cleared after failure and before propagation or tolerated continuation, retaining another genuine session's marker. |
| `after-interrupted` | Real native interruption settles and owned cleanup completes; interrupt acknowledgement alone is insufficient. |
| `captured-dispose`, `captured-reload` | A genuine model request holds its native tool snapshot while registrations are explicitly disposed or the plugin is unloaded; releasing the model call cannot escape the closed owner generation. |
| `running-dispose` | An already-running owned callback cannot continue after disposal, even though disposal does not erase a captured hook array. |
| `stale-completion-reuse` | Stale completion cannot recreate revoked state; a subsequent real native call must not execute without an active owner fence. |

For critical, rejected or disposed running handlers the diagnostic also requires
the entire native session to end `failed` (or `interrupted` for interruption).
That session-level target is **stricter** than the legacy owned-dispatcher rule,
which requires targeted revocation and propagation of the tool error but does
not require the enclosing session to fail. A successful session after a surfaced
tool error violates this added target; it does not by itself show lost errors or
failed revocation. The report retains tool and session outcomes separately.

The test wrapper delegates to the captured builtin Effect executor with its
genuine native context. It never supplies a custom shell service or manually
invokes a saved executor with fabricated context. Registration disposal and
plugin unload are distinct observations. Synthetic state cannot unlock any
production runner or capability.

The pinned shared error constructor is the `Error` export from
`@opencode/plugin/promise/tool`, supplied by the host. The root plugin module
does not export a value named `Tool`. The controller awaits native activation
through the agent-list endpoint before reading the plugin inventory; a single
early `plugin.list` snapshot can be empty while activation is still pending.

## Isolation and bounds

- Fresh owned HOME/XDG/cache/data/state/DB/TMP and a fixed child environment
  allowlist; no inherited credentials, service/session, loader or proxy overrides.
  Ancestor/system/managed configuration causes preflight refusal, not a bypass.
- Every private foreground server uses fresh child-only Basic authentication and
  an explicit loopback URL. `/api/info.pid` must match the unreaped owned process
  before API mutations. No service discovery or shared-server control calls.
- Local fixture plugins and host-supplied SDK modules only. Fixed harmless shell
  witnesses; no package-manager invocation, including negative install attempts.
  Tripwires are defensive, not an OS sandbox or general network firewall.
- Primary work is capped at 50 seconds per case, with 10 seconds reserved for
  teardown. Barriers wait outside the provider lock, are bounded, and release on
  every failure path. Prompt admission, idle wait and terminal history are
  different evidence, not interchangeable acknowledgements.
- At most 16 accepted provider/control connections and requests per case; headers
  time out before parsing, requests cap at 1 MiB, child stdout/stderr continuously
  cap at 128 KiB each, and trace caps at 128 rows/128 KiB. The authenticated native
  API has a separate 24-request cap to include PID checks and the second reuse
  attempt. A case-wide watchdog cancels sockets at the absolute primary deadline;
  inactivity timeouts alone do not establish that bound. Unknown protocol traffic
  fails collection rather than disappearing into an omitted trace.
- Teardown releases barriers, closes accepted sockets, terminates/reaps only the
  owned group, and joins all writers/readers. Root device/inode/ownership is
  checked before deletion. Unsafe or unsettled roots are retained and measurement
  fails. Reports omit credentials, raw contexts, environment values and arbitrary
  native diagnostics.

## Evidence and remaining gates

An independent run on 2026-11-03 collected all 18 cases with **measurement PASS**
and **profile UNQUALIFIED**. The installed executable's separately measured
SHA-256 was `abe4d88594bffb12b364375b8a6732d2d1f7a977195ed1a35c5c76f8e89c9e0e`.
That is a measurement of this host, not an asserted release-archive hash or a
guarantee for another installation.

- The baseline, plugin-policy controls, missing/failed owner, topology change,
  native post-shell permission check and three owned field-binding controls all
  produced their required observations. The captured executor denied execution
  after explicit disposal and, separately, after scope-finalizer unload.
- For critical and rejected owned AFTER handlers, the native tool ended `error`,
  the consumer received the owned error, targeted synthetic state was cleared and
  the other session's marker remained. The enclosing session nevertheless ended
  `succeeded`. Running-disposal and stale-completion cases also ended with a
  successful session after a terminal tool error. These are violations of the
  extra session-level target above, **not** evidence of lost tool errors.
- In the stale-completion case, a running callback observed the closed owner and
  was rejected after explicit registration disposal. A **fresh** native request
  with a distinct call then ran the fixed harmless reuse witness, completed with
  exit 0 and reached the consumer. The removed wrapper did not fence this new
  executor. The observation rules out treating disposal as a durable guard.
- The host replayed the tool transform during reload. Each recorded definition
  still identified the native shell; transform replay is not counted as tool
  execution. Native executor entry and terminal call identity are checked
  independently.

The independent verifier inspected each owned fixture before deletion and
correlated native session, message, call and terminal state against the disposable
database using its actual schema. All 18 roots, processes, threads and sockets
settled and were removed. Selected real configuration, authentication and service
registry bytes/inodes and existing runtime process identities matched before and
after. These are before/after observations, not an OS sandbox or proof against
transient external writes. Earlier failed startup and incomplete-matrix attempts
were retained separately rather than rewritten as success.

Pinned implementation evidence is official tag `v2.2.5`, source commit
`9bbb8ce18c80f099e0e448775f59d965ead40a21`. Release archive SHA-256
`25ba9908979fa7d764792c82589b4b5768ab1511154e0317d98aa77d216ce767`
is not the installed executable hash; the driver measures that separately and
checks its identity again after the suite. Rolling V2 docs describe APIs, not a
future guarantee for this implementation.

Any production route still needs separately selected backend integration,
raw-receipt/one-shot runner correctness, effective profile ownership and binary
continuity, broader turn/compaction/deletion/reload lifecycle guarantees and
independent review. Child evidence never grants parent interactive authority.
No upstream patch, global activation or frontend manager contract is selected.

References: [V2 plugins](https://opencode.ai/v2/docs/build/plugins),
[Effect](https://opencode.ai/v2/docs/build/plugins/effect),
[server hooks](https://opencode.ai/v2/docs/build/plugins/server),
[API](https://opencode.ai/v2/docs/api),
[existing dependency workflow](../dependency-security-workflow.md).
