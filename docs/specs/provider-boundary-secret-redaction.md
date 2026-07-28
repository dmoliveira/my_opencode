# Provider-boundary secret redaction

## Security contract

The gateway scans the complete provider-bound message history immediately before
dispatch. Mutable prompt, system, tool, summary, and other content fields are
redacted in place. Secret-pattern matches in protocol identifiers, URLs,
metadata, unknown fields, or object keys block dispatch without logging the
matched value.

OpenAI reasoning replay is one narrow exception. The gateway preserves
`parts[index].metadata.openai.reasoningEncryptedContent` without regex scanning
only when the same message and part have own data properties proving this exact
shape:

- `info.role` is `assistant`;
- `info.providerID` is `openai`;
- the part type is `reasoning`;
- `metadata.openai.itemId` matches `rs_.+`; and
- the encrypted content is a non-empty own string value.

This field is opaque provider-produced replay state. It must remain unchanged;
regex replacement would corrupt subsequent OpenAI requests, while token-shaped
substrings occur naturally in ciphertext. The ciphertext still consumes all
resource budgets. Wrong paths, malformed shapes, inherited qualifiers,
accessors, aliases visited through an untrusted path, and neighboring metadata
remain scanned and fail closed.

OpenCode tool-state UI metadata is also projected according to the reviewed
OpenCode `1.18.0` conversion contract (upstream commit
`3f9dad3fd0d4ce01ccb443896bce93d9e7f390eb`). For completed, pending, and
running tool parts, `state.metadata` is not dispatched and is not scanned. For
error parts, only an own string `state.metadata.output` is scanned and redacted,
and only when an own boolean `interrupted` is `true`. A genuinely absent output
falls back to separately scanned `state.error`, matching OpenCode. A false or
genuinely absent `interrupted` value leaves metadata undispatched. Inherited,
accessor, non-boolean, inherited/accessor-output, non-string-output,
unknown-status, or malformed control shapes block rather than earning this
projection. `state.input`,
`state.output`, `state.error`, attachments, and separate `part.metadata` remain
provider-bound and scanned. Aliasing skipped metadata into one of those paths
causes it to be scanned through that path.

## Resource limits

Tool-output and provider-system redaction retain the shared `maxDepth`,
`maxNodes`, and `maxChars` limits. Provider message histories use additional
call-wide limits because a valid resumed session can be much larger than one
tool result:

- `providerMaxMessages`: `20,000`
- `providerMaxNodes`: `1,000,000`
- `providerMaxChars`: `134,217,728`
- `providerMaxMessageChars`: `16,777,216`

`providerMaxChars` and `providerMaxMessageChars` include traversed regex-scanned
text and preserved ciphertext. Local UI-only tool metadata is not traversed or
charged because the reviewed converter does not dispatch it. Public
`scannedChars` telemetry counts only text actually checked against secret
patterns. Provider traversal revisits shared objects at each path, so a
trusted-path visit cannot hide an untrusted alias; every revisit is charged to
the same bounded call.

For backward compatibility, explicitly configured legacy limits seed all
corresponding provider limits until the new keys opt in. Legacy `maxNodes`
becomes the `providerMaxNodes` fallback and caps the default
`providerMaxMessages`; legacy `maxChars` becomes the `providerMaxChars` and
`providerMaxMessageChars` fallback. Explicit provider keys take precedence.
`providerMaxMessages` cannot exceed `providerMaxNodes`, and
`providerMaxMessageChars` cannot exceed `providerMaxChars`.

## Required validation

- exact and one-over resource-boundary tests;
- positive and negative OpenAI replay-shape tests;
- alias, cycle, depth, malformed-property, and unknown-field tests;
- gateway lint, build, full tests, and provider-boundary live smoke; and
- bounded fork probes of affected sessions using the candidate plugin build,
  with source sessions unchanged and test forks removed afterward.

The tool-state projection must be reverified whenever the supported OpenCode
message converter changes; converter drift is a fail-closed release risk.
