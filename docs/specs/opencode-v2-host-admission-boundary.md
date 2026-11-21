# OpenCode V2 host-level shell admission boundary

Status: **host change required; not implemented or qualified**. This contract
does not authorize the V2 gateway, execution-status writer, or sidebar.

## Why a plugin hook is not the admission boundary

Pinned OpenCode 2.2.5 source at commit
[`9bbb8ce18c80f099e0e448775f59d965ead40a21`](https://github.com/anomalyco/opencode/tree/9bbb8ce18c80f099e0e448775f59d965ead40a21)
shows two relevant paths:

- The [`shell.create` HTTP handler](https://github.com/anomalyco/opencode/blob/9bbb8ce18c80f099e0e448775f59d965ead40a21/packages/server/src/handlers/shell.ts)
  calls `Shell.Service.create` directly. It does not carry the agent-tool
  `tool.use` permission context, so that policy alone cannot cover direct API
  shell creation.
- The [core shell service](https://github.com/anomalyco/opencode/blob/9bbb8ce18c80f099e0e448775f59d965ead40a21/packages/core/src/shell.ts)
  builds an invocation, runs registered `shell.create.before` hooks and its
  optional caller callback, then derives shell arguments and spawns the process.
  A check that runs before those hooks is not a check of the final process
  inputs.

Existing synthetic measurements observed a trusted fixture hook changing the
shell and `BASH_ENV` so a startup file ran a command denied by command-text
policy. This demonstrates that command-text policy does not bind all process
inputs; it is not a plugin-sandbox escape. The dependency-profile probe also
observed a fresh native request execute after a plugin wrapper had been disposed.
These observations are bounded to their tested fixtures and versions; they do
not prove that every hook or host release behaves the same way. See the [native boundary contract](opencode-v2-dependency-boundary-contract.md),
[dependency-profile probe](opencode-v2-dependency-profile.md), and
[direct-shell activation measurement](../../plugin/gateway-core/test/v2/direct_shell_activation_live_smoke.py).

This is source inspection of the pinned release, not proof of the installed
service's identity or behavior. A plugin-only change in this repository cannot
add an immutable final check inside OpenCode core.

## Required host contract

An upstream implementation must provide all of the following before a V2
gateway can rely on shell admission:

1. **One host-owned gate before spawn.** Every process-creating shell entry point,
   including direct `shell.create` API calls and model-driven shell execution,
   must reach a host-owned admission decision. It must run after every mutable
   plugin/callback transform and immediately before process creation.
2. **Bind the final launch tuple.** The gate must inspect the exact final command,
   argv, executable resolution, working directory, environment, timeout, and
   trusted session/call identity that the spawner will consume. Freeze that tuple
   for both the decision and spawn; do not validate one object and later read
   mutable fields from another.
3. **Use host-derived identity and policy.** Do not infer a session or call from
   callback order, copy it from an untrusted payload, or treat `tool.use` as the
   direct API's authorization. If the host cannot establish the required trusted
   context, it must refuse admission.
4. **Fail closed through startup and lifecycle changes.** Missing, pending, or
   failed policy initialization, unexpected hook/config topology, and policy
   errors must not fall back to an unguarded native executor. Disposal, unload,
   reload, and a later fresh request must not reopen admission accidentally.
5. **Make denial precede execution.** A rejected request must not spawn a child
   or run a shell startup file. A denial response or audit record is not enough;
   tests must independently check process and witness evidence.

This boundary is about host process admission. It does not claim to sandbox
trusted plugins that already execute with host authority, and it does not replace
the separate provider, transport, lifecycle, or runtime-data gates.

## Required regression matrix

Tests must run against the patched host implementation, not a plugin-only
simulation, with fresh synthetic runtime data and a controlled localhost
provider. At minimum, cover:

| Case | Required evidence |
| --- | --- |
| Allowed control | The admitted frozen tuple is the tuple actually spawned; output and exit are correlated to that request. |
| Direct API denial | A denied direct `shell.create` call is refused even without agent-tool permission context; no child or witness appears. |
| Late command/cwd/executable/environment mutation | A later hook cannot change an earlier-approved tuple into a different spawned process. Test each field independently. |
| Startup environment | A late shell/`BASH_ENV` mutation cannot run a denied startup command before the host's final decision. |
| Admission not ready | Direct API and model calls cannot execute before the host gate is active, or when policy initialization fails. |
| Disposal and reload | Captured executors and fresh requests after disposal/unload/reload cannot reach an unguarded native executor. |
| Policy error or cancellation | Failure before spawn leaves no child or witness and does not leave reusable admission state. |

Correlate the request, host decision, final launch tuple, child process identity,
and terminal result. A hook callback, API error, or missing witness by itself is
not sufficient evidence. Keep allowed controls so the test distinguishes a
working gate from a disabled shell.

Run live qualification only with synthetic histories and independently verified
OS restrictions on filesystem writes, outbound network, and signals. Record the
selected executable identity before and after the suite. Private homes,
pathname-based fixtures, and process-group teardown are not substitutes for an
OS sandbox; retain probe fixtures on every outcome and inspect them before
sharing or cleanup.

## Exit criteria and limits

This gate passes only after a host implementation and version-pinned tests meet
the contract above, with independently reviewed evidence. Passing it would
qualify only the measured shell-admission boundary. It would not clear the
remaining transport/provider, lifecycle, V2-native session, or strict snapshot
validation gates in the [migration inventory](../plan/doing/opencode-v2-migration.md).
Keep the V2 gateway, status writer, and sidebar unconfigured until those gates
also pass. Do not weaken V1 snapshot validation or infer repair safety from
synthetic claims.
