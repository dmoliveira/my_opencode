# Owner-bound execution admission: proposed contract

Status: **design proposal only**. This document does not implement or activate a
guard, qualify a profile, or grant dependency authority. The measured V2 profile
remains **UNQUALIFIED**, with authority `disabled-unqualified`. The separately
documented [Python/uv workflow](../dependency-security-workflow.md) is unchanged.

The [isolated profile measurement](opencode-v2-dependency-profile.md) observed a
fresh native call execute after an owned wrapper was disposed. A captured-call
fence alone therefore cannot establish the intended owner-loss guarantee. The
[earlier boundary observations](opencode-v2-dependency-boundary-contract.md)
also leave final-input binding, raw-result ordering and lifecycle revocation
unproven. These observations motivate the requirements below; they do not show
that the current host satisfies them.

## Scope and trust

The proposed boundary covers every execution entry point included in a selected
profile, including requests originating outside the model tool loop. The profile
must explicitly identify its covered operations, callers and lifecycle events.
An omitted, unknown or unverified path cannot inherit authority from a successful
check on another path. A path capable of reaching a protected effect must be
mediated or independently prevented within the stated trust boundary; calling it
out of scope is not evidence that it cannot reach that effect.

A trusted enforcement component must remain able to deny execution when the
owner or its removable registrations are absent. It must mediate the final
handoff, not merely observe plugin inventory or an earlier request. A component
that disappears with the owner cannot be the only enforcement boundary. The
existence and coverage of such a component are **not established** here.

The host, enforcement component, identity source and selected dependencies of
the guard are in the trusted computing base. Policy does not sandbox code already
running with host privileges. Hostile same-privilege interference, untrusted
extensions or protected resources outside that trust boundary require separately
specified and verified isolation. Hashes can establish continuity after an
initial trust decision; they do not establish initial authenticity.

## Lifecycle

The following states describe required behavior, not a proposed API:

| State | Required behavior |
| --- | --- |
| **Closed** | Deny new protected execution. Startup, missing ownership, uncertainty and failed verification begin here. |
| **Verifying** | Establish a non-reusable owner generation and validate its host, configuration, identity source and policy. Failure returns to Closed. |
| **Active** | Admit only operations that satisfy the current generation's complete contract. |
| **Draining** | Refuse new handoffs, invalidate pending authority and account for previously handed-off work. |
| **Quarantined** | Remain closed while affected authority or in-flight work is uncertain; reopen only after required settlement and a new verification. |

Owner disposal, unload, reload, owner expiry or failure, and loss of a required
enforcement component close and drain the affected profile. An individual
operation's expiry, cancellation or failure revokes only its affected authority
and preserves unrelated sessions' pending state and authority. If the affected
scope cannot be established, use the conservative closure rule below.

Session deletion and compaction invalidate the affected authority; other relevant
turn and lifecycle transitions need explicit invalidation rules. Generation
identities must not repeat across relevant restarts or recovery. If non-reuse
cannot be established, admission stays closed. Recovery starts closed; no prior
permission or completion may be promoted into a new generation.

## Admission and handoff invariants

1. **Trusted identity.** The boundary obtains caller, session and call identity
   from trusted runtime state. Caller-supplied identifiers, output or status text
   are not authority. Missing or ambiguous required identity denies the request.
2. **Bounded, one-use permission.** A permission binds the owner generation,
   authenticated principal, trusted session and consuming call identity,
   operation, scope, expiry, relevant receipt and final execution inputs. It
   cannot be transferred, replayed or reused. Stale or unrecognized permissions
   fail closed. Authority material stays within the trusted boundary, not in
   model-visible content or caller-editable state.
3. **Final-input continuity.** The decision covers the final command or
   operation, working directory, executable, environment and relevant protected
   inputs after transformations. An earlier check does not establish that these
   values remain unchanged at handoff.
4. **One ordering point.** Generation and expiry validation, one-use consumption
   and in-flight registration must be coordinated with closure at the final
   handoff. If closure wins, no new handoff occurs. If handoff wins, the work is
   recorded as in flight before closure can complete. An implementation that
   cannot establish this ordering must remain closed or use an independently
   verified containment boundary.
5. **No stale completion.** A completion from an old generation or call cannot
   recreate authority or alter newer pending state in the same session or another
   session's pending state. Failure and cancellation revoke the affected
   authority without clearing unrelated sessions.

If trusted identity is missing or ambiguous and the boundary cannot identify
which existing authority was affected, it closes the affected profile,
quarantines potentially affected authority and accounts for relevant in-flight
work. It must not invent a session or guess which unrelated session to clear. A
malformed request proven unrelated to existing authority may be denied locally.

The trust model must also say how configuration, executable and input continuity
are protected between validation and actual use. It must not assume that a file
hash or a process identifier alone closes that interval.

## Loss, settlement and recovery

On owner loss, deny further handoffs and revoke unconsumed permissions. For work
already handed off, request termination where supported and track owned work and
its descendants until their actual state is known. An acknowledgement, timeout
or signal request is not evidence of settlement. Missing or contradictory
evidence keeps the boundary closed and the affected work quarantined.

An already-started operation can have irreversible external effects, including
effects occurring while termination is in progress. This contract does not
promise rollback or instantaneous cessation. Any stronger guarantee requires a
separately established containment mechanism and a defined reconciliation
procedure. Abrupt host or owner loss likewise requires a surviving trusted
supervisor or an equivalent recovery prerequisite; otherwise uncertain in-flight
work remains unresolved and admission stays closed.

## Evidence and qualification gates

Before any production authority is considered, independent verification must
establish the selected boundary's coverage, trusted identity, final-input binding,
handoff ordering, revocation and recovery behavior. It must cover missing or
failed ownership, captured and fresh calls, concurrent sessions, cancellation,
identity uncertainty, reload and restart, generation non-reuse, and the cases
where settlement cannot be established.

The separate raw-result and dependency gates remain necessary: authoritative
results must be correlated to the actual call before presentation changes, and a
successful result must not be inferred from a session outcome alone. Redacted
evidence should distinguish admission decisions, tool results, session outcomes,
revocation and verified settlement without exposing credentials or private
consumer data. Missing evidence is a refusal, not a pass.

A design, a static source review or a synthetic observation cannot itself enable
the guard, authorize a package operation or qualify a frontend dependency
workflow. Any implementation and its deployment need their own reviewed scope,
validation and explicit authority decision.
