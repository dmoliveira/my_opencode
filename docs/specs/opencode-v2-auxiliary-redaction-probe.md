# V2 auxiliary request redaction probe

Status: **synthetic measurement only**. This probe does not install or configure
the gateway, establish a security boundary, or grant authority. The V2 gateway
and dependency profile remain **unqualified**.

## Run

With Python 3.11+, an existing gateway build environment, and OpenCode 2.2.5:

```sh
make gateway-v2-auxiliary-redaction-probe OPENCODE_BIN=/path/to/opencode
```

The target builds `plugin/gateway-core` and runs the probe. It does not install
dependencies. To select a private fixture parent, invoke the script directly
after the build with `--temp-parent <directory>`. A disposable home is not an OS
sandbox; choose an isolated environment when preserving local data is critical.

## What it measures

Two separate private authenticated runtimes use an owned local plugin and a
synthetic OpenAI-compatible provider listening on loopback. Each case uses
different random provider and trace credentials. The control does not register the
redactor; the protected case registers only the existing experimental context
redactor. For each native `context`, `title`, `generate`, and `compaction` hook,
the fixture introduces a synthetic system canary and supplies a separate
synthetic message canary. It checks the hook inputs and outputs, then independently
checks the provider's received request for both canaries and positive markers.

The control must deliver both canaries for every kind. The protected case must
remove both and retain redaction and positive markers for every observed request.
Unknown, duplicated hook, missing, malformed, or ambiguous evidence is a failure.
More than one provider request per hook is allowed; each is checked.
The report contains counts, finite reason codes, fixture basenames, and the
selected executable's SHA-256, not request bodies, session IDs, or canary values.

The probe awaits location activation and confirms its local plugin before creating
a synthetic session. It distinguishes admitting compaction from observing a
compaction request: receipt of that request does **not** establish that compaction
completed. It uses fresh HOME/XDG/DB paths, an environment allowlist, a private
server password, PID checks before API mutations, bounded output/requests/time,
package-manager stubs that exit without writing, and owned-process teardown. The
stubs only cover the listed commands found through the child `PATH`; they do not
detect every attempted installation or replace network isolation. System or
ancestor OpenCode configuration causes preflight refusal. All fixture roots,
including version probes, are retained under the selected temporary parent;
the probe's unit tests also retain their temporary fixture roots. Teardown reports
whether owned processes and sockets settled. Retained fixtures contain synthetic
prompts and may contain local runtime metadata; inspect them before sharing or
cleaning them up. The selected executable is version-checked
and its identity is compared before and after; that does not prevent a transient
swap. Hook witnesses travel over an authenticated localhost channel, not a trace
file; its key is present in the retained synthetic plugin, and the provider key
is present in its retained configuration. Fixture paths, channel authentication,
and metadata checks do not establish protection against a hostile process with
the same user identity.

## Observed result and limits

On 2026-11-06, one local executable reporting `opencode v2.2.5` produced one
context, one title, one generate, and two compaction provider requests in each
case. Its SHA-256 was
`abe4d88594bffb12b364375b8a6732d2d1f7a977195ed1a35c5c76f8e89c9e0e`.
Both canaries reached the control provider and were absent from every protected
observation. These results describe that executable and synthetic run, not every
binary reporting the same version or other versions.

The probe does not test a later hook changing content after redaction, transport
hook ordering, WebSocket, streaming semantics, other providers or encodings,
images, large or resumed histories, or the complete secret detector. It does not
prove event completeness or production isolation. The separate
[owner-bound admission proposal](opencode-v2-owner-admission-proposal.md) and
[dependency-profile measurement](opencode-v2-dependency-profile.md) retain their
unresolved activation gates.
