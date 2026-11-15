# Native V2 interruption settlement probe

Status: **measurement only**, not a security boundary or authorization. The
experimental adapter and V2 gateway remain unconfigured and unqualified.

## Run

With Python 3.11+, the existing built gateway files, and OpenCode **2.2.5**:

```sh
make gateway-v2-native-settlement-probe OPENCODE_BIN=/path/to/opencode
```

The target does not build or install dependencies. If the adapter source changed,
build `plugin/gateway-core` first. The script accepts `--temp-parent <directory>`
and emits one JSON report when invoked directly. Other executable versions fail
instead of inheriting these observations.

**Run within an independently verified OS sandbox when local data must be
preserved.** Private homes, channel credentials and identity checks do not stop
same-user interference or establish filesystem containment. Independently
verify filesystem-write, outbound-network and signal restrictions; this probe
is not itself a sandbox.

## What is measured

An authenticated private server loads only an owned fixture plugin alongside
built-ins and uses a synthetic localhost provider. The controller creates two
distinct sessions and verifies server PID before each API mutation. A fixture
pre-context hook holds the target execution. The fixture **injects** a synthetic
tool-error event into the registered adapter callback, but delegates its
`interrupt` and `wait` calls to the actual host session APIs.

After the first interruption is accepted and the first native wait returns, the
fixture deliberately holds that result before delivering it to the adapter. A
second target execution starts, then a second real interruption is accepted. A
separate peer session reaches the provider with a synthetic marker. The first
wait result is released; the probe requires a second native wait, checks the six
captured guard callbacks while its result is held, and checks release after that
result is delivered. The six guard checks are direct callback invocations, not
six independently observed native provider requests. Trace and controller
traffic use per-run authenticated localhost channels; reports omit session IDs,
credentials, request bodies and arbitrary native diagnostics.

The control intentionally delays wait delivery and injects errors. It does not
establish that this scheduling occurs naturally, that `session.wait` identifies
an interruption generation, or that the host settled independently running
shells, background jobs, another service, or another provider transport. It
does not test unload/restart, crash recovery, or every request kind and version.

## Retention and result limits

All case and version fixture roots are retained on success and failure. Reports
include their basenames, selected executable and adapter hashes, and checked
process/socket teardown. Retained data contains synthetic credentials, prompts
and runtime metadata; inspect it before sharing or cleaning it up. Teardown
does not prove no process escaped the checked group. Hash and fixture identity
checks do not prevent transient replacement or same-user races.

On 2026-11-15, a restricted tmux run of the selected 2.2.5 executable observed
two accepted native interruptions and the required two native waits; the peer
marker reached the local provider. A separate retained baseline control using
the adapter from commit `c52a8832` observed the old guard reopen after the
delayed first result and before a second wait. That baseline control is not part
of the reusable command. Both are bounded synthetic observations, not proof of
gateway protection or compatibility for other executables reporting 2.2.5.
