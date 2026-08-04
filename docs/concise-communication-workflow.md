# Concise Communication Workflow

Use this module when the user, runtime, or repo default wants lower-token, higher-density answers without losing technical accuracy.

## Mode model

- `off`: normal repo communication style
- `lite`: remove filler and hedging, keep normal sentence structure
- `full`: prefer short direct fragments while keeping technical terms exact
- `ultra`: strongest safe compression only

## Precedence

1. explicit user request
2. runtime/plugin mode
3. repo default in `AGENTS.md`

If a runtime exposes concise controls, treat its effective mode status output as the source of truth.

## Core rules

- Preserve technical substance; remove fluff first.
- Keep code blocks, commands, identifiers, filenames, flags, and exact errors unchanged.
- Short fragments are fine when meaning stays obvious.
- Expand again when compression would hide risk, blockers, or ordering.

## Good concise targets

- validation summaries
- progress updates
- review summaries
- PR/release notes
- routine operational status

## When to relax concise mode

- destructive or irreversible warnings
- security/privacy guidance where nuance matters
- multi-step instructions where compressed wording could reorder meaning
- repeated confusion or explicit requests for more detail

## Boundaries

- Do not compress away blocker evidence, validation evidence, or final state.
- Do not force terse output when clarity would become unsafe.
- Keep the module easy to disable or override.

## Runtime context compaction

The gateway uses a versioned compact provider contract for its built-in fallback
and for the reviewed canonical concise skill. Canonical matching hashes
`exactPromptFingerprint([normalizedBody])`, where `normalizedBody` is the
existing frontmatter-stripped, trimmed body; line endings and internal
whitespace are not normalized. The registered `canonical-v1` fingerprint is
`bf27645f37241c9c852c030192f582a341d04376286a90e9c34bf5635d596580`.

- Exact canonical copies intentionally use the compact contract.
- Unknown, customized, or revised skill bodies pass through unchanged after
  existing loader normalization and retain their mode-specific runtime rule.
- Resolved mode source remains in gateway state/audit, not provider prose.
- `review` and `commit` keep their specialized runtime rules.
- Managed order remains stable guidance, concise context, then the unique
  session context.

For the fixed `lite` + `session-fixed` fixture, managed context falls from
1,548 to 656 characters: 892 fewer (57.6%). This measures recurring provider
input/context only, not cache hits, latency, cost, or provider token budgets.
Rollback requires reverting the single delivery commit, rebuilding/redeploying
the gateway, and restarting OpenCode; no config or state migration is involved.
