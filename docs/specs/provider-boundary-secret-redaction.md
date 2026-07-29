# Provider-boundary secret redaction

## Security contract

The gateway scans the complete provider-bound message history immediately before
dispatch. Mutable prompt, system, tool, summary, and other content fields are
redacted in place. Except for the bounded opaque envelopes defined below,
secret-pattern matches in protocol identifiers, URLs, metadata, unknown fields,
or object keys block dispatch without logging the matched value.

Provider messages and system values must be JSON-shaped data: records use the
ordinary or null prototype, arrays use the standard array prototype, the global
`Object.prototype` has its standard unextended key set, and every traversed child
is an own enumerable data property. Proxies, functions/callable proxies, custom
prototypes, accessors, non-enumerable or symbol properties, sparse arrays, extra
array properties, `undefined`, bigint, and non-finite numbers block as
`malformed_provider_object`. The traversal reads property descriptors rather
than invoking getters, preventing a value from changing between validation and
dispatch scanning.
Audit fallback session-ID extraction uses the same proxy-safe own-data
descriptor rule and never invokes message accessors before validation.

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
OpenCode `1.18.5` conversion contract (tag commit
`e5cc278dec9294a627a7b05f47ce6a564408c1a2`). The reviewed converter is
`packages/opencode/src/session/message-v2.ts`, blob
`1bea9f52c3ec6afec280e176a930c747c72091b7`; its relevant reasoning and tool
projection is byte-identical to `1.18.0`. The transform-before-conversion
ordering is pinned by `packages/opencode/src/session/prompt.ts`, blob
`eb116f6b960f6da4115ffb262695af6162ac2045`. For completed, pending, and running
tool parts, `state.metadata` is not dispatched and is not scanned. For error
parts, only an own string `state.metadata.output` is scanned and redacted, and
only when an own boolean `interrupted` is `true`. A genuinely absent output falls
back to separately scanned `state.error`, matching OpenCode. A false or
genuinely absent `interrupted` value leaves metadata undispatched. Inherited,
accessor, non-boolean, inherited/accessor-output, non-string-output,
unknown-status, or malformed control shapes block rather than earning this
projection. `state.input`,
`state.output`, `state.error`, attachments, and separate `part.metadata` remain
provider-bound and scanned. Aliasing skipped metadata into one of those paths
causes it to be scanned through that path.

### Canonical PNG attachment envelope

A completed OpenAI tool-result PNG can contain a Google-key-shaped substring in
its Base64 transport by chance. The affected production history contained one
such attachment, so the finalizer blocked before making any provider request.
The same owner-only history replay produced one 3.89 MB `/v1/responses` request
when the guard was disabled, proving that request size was not the blocker.

The gateway omits only the one explicitly designated detector at the built-in
default-pattern index, and only when it is exactly
`AIza[0-9A-Za-z\-_]{20,}`, for one canonical, structurally valid PNG container.
An explicit pattern-list override receives no designation, even if it contains
that exact expression. A duplicate, equivalent-source, or differently flagged
detector also remains enforcing. Every other configured detector still scans
the URL. The exception requires own data properties and identity checks proving
this shape:

- an assistant message routed through provider `openai` with non-empty message
  and session IDs;
- `parts[index]` is a tool part with non-empty tool, call, part, message, and
  session IDs, and the part references match the containing message;
- the tool state is `completed`, has an own time record, and has not been
  compacted; and
- `state.attachments[index]` is an own file attachment with non-empty IDs,
  `mime: image/png`, and an exact canonical `data:image/png;base64,...` URL.

OpenCode import and fork remap the containing message and tool-part references
but can retain the source IDs inside nested attachment records. The reviewed
converter does not use those nested IDs for dispatch, so they must be present
but are not required to equal the remapped message. All other container
identities are checked exactly. Proxies, custom prototypes, accessors,
non-enumerable or inherited qualifiers, malformed shapes, compacted tool states,
other media types, and aliases reached through an unqualified path fail closed.

The URL validator caps the complete URL at `16,777,216` characters, decoded
bytes at `12,582,912`, chunks at `16,384`, each dimension at `32,768`, and total
pixels at `100,000,000`. It requires canonical standard Base64, exact
round-trip encoding, PNG signature and chunk boundaries, CRCs, valid IHDR and
PLTE controls, contiguous IDAT chunks, known critical chunks, and a unique final
IEND with no trailing bytes. It validates a PNG container, not decompressed
pixels or image meaning: IDAT inflation, textual metadata, OCR-visible secrets,
steganography, and authenticated attachment origin remain outside this regex
DLP guarantee. CRC establishes transport integrity, not trust.

This path is pinned to OpenCode `1.18.5` and its reviewed `message-v2.ts`
converter above. OpenCode pins `@ai-sdk/openai` `3.0.84`; the reviewed Responses
converter is
`packages/openai/src/responses/convert-to-openai-responses-input.ts` at commit
`da385f747e8277411d8b49c65e8a22c3bf158f4c`. It serializes tool-result image
data as one `input_image` inside `function_call_output.output`. Converter drift
must fail closed until this contract is reverified.

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
text, preserved ciphertext, and qualified PNG URLs. Local UI-only tool metadata
is not traversed or charged because the reviewed converter does not dispatch
it. Public `scannedChars` telemetry counts the PNG URL once because every
configured detector except the one transport-incompatible Google detector still
checks it. Provider traversal revisits shared objects at each path, so a
qualified-path visit cannot hide an unqualified alias; every revisit is charged
to the same bounded call.

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
- canonical PNG collision, provenance, alias, parser, resource, and performance
  boundary tests, including exact overrides, duplicate/equivalent detectors,
  and other custom detectors that must still block;
- alias, cycle, depth, proxy/callable, custom/prototype-polluted, accessor,
  non-enumerable, symbol, sparse/extended-array, malformed-primitive,
  malformed-property, and unknown-field tests;
- assembled-plugin default-versus-legacy resume regression tests;
- gateway lint, build, full tests, and provider-boundary live smoke;
- credential-free `make gateway-resume-redaction-e2e`, which imports a private
  synthetic large session, forks it through OpenCode `1.18.5`, and requires
  native OpenAI localhost dispatch with exact ciphertext, redaction, metadata
  projection, one exact PNG `input_image`, source-integrity, audit, and cleanup
  assertions; and
- an owner-only export/import replay of the affected session using the candidate
  build and localhost capture, requiring one image-bearing provider request,
  unchanged source message/part digest, no host credentials, and complete
  sandbox cleanup.

The tool-state projection must be reverified whenever the supported OpenCode
message converter changes; converter drift is a fail-closed release risk. The
credential-free resume gate is mandatory CI and future release acceptance. Its
exact OpenCode version pin, converter evidence above, CI installation pin, and
test expectations must be reviewed together before a version change can pass.

`providerID` is a runtime routing label, not cryptographic provenance. The
ciphertext exception is intended only for trusted provider-produced state. The
test harness deliberately imports synthetic state to exercise the complete
resume transport boundary; that fixture does not broaden the production trust
claim for arbitrary imported sessions.
