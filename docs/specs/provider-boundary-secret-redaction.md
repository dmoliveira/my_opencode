# Provider-boundary secret redaction

## Security contract

The gateway scans the complete provider-bound message history immediately before
dispatch. Mutable prompt, system, tool, summary, and other content fields are
redacted in place. Except for the bounded opaque envelopes defined below,
secret-pattern matches in protocol identifiers, URLs, metadata, unknown fields,
or object keys block dispatch without logging the matched value.

The built-in OpenAI-key detector is left-token-bounded as
`\bsk-[A-Za-z0-9_\-]{20,}`. It detects keys at the start of a value or after
punctuation or whitespace, but does not mistake an `sk-...` suffix inside an
ordinary identifier such as `task-validation-accounting` for a secret. Explicit
custom patterns are not boundary-rewritten and can intentionally retain broader
matching.

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
- `metadata.openai.itemId` is genuinely absent or is an own string matching
  `rs_.+`; and
- the encrypted content is a non-empty own string value.

This field is opaque provider-produced replay state. It must remain unchanged;
regex replacement would corrupt subsequent OpenAI requests, while token-shaped
substrings occur naturally in ciphertext. The ciphertext still consumes all
resource budgets. A null, empty, wrong-prefix, inherited, or accessor-backed
item ID does not qualify. Wrong paths, malformed shapes, aliases visited through
an untrusted path, and neighboring metadata remain scanned and fail closed.

OpenCode tool-state UI metadata is also projected according to the reviewed
OpenCode `1.18.18` conversion contract (tag commit
`31406ccc51b4bd2a4e1e086b2bcaa5f7f804f26d`). The reviewed converter is
`packages/opencode/src/session/message-v2.ts`, blob
`9b3f2c46f40578128001957004c67633a18da23a`; it hydrates message and part IDs
from the SQLite rows before provider processing. The transform-before-conversion
ordering is pinned by `packages/opencode/src/session/prompt.ts`, blob
`22b1d7d99a2aa22211b5dae59385fa8a8a1d311d`. For completed, pending, and running
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

### Canonical provider attachment envelope

A direct user file or completed OpenAI tool-result attachment can contain a
Google-key-shaped substring in its Base64 transport by chance. The finalizer
must not block a canonical opaque binary payload before making a provider
request. The reviewed converter carries PNG and JPEG as image media and PDF as
file media for both supported attachment shapes.

The gateway omits only the one explicitly designated detector at the built-in
default-pattern index, and only when it is exactly
`AIza[0-9A-Za-z\-_]{20,}`. Each omitted match must lie wholly inside the
canonical Base64 payload of an allowed attachment. A match in or crossing the
header remains blocking. An explicit pattern-list override receives no
designation, even if it contains that exact expression. A duplicate,
equivalent-source, or differently flagged detector also remains enforcing.
Every other configured detector still scans the complete URL.

The exception requires own data properties and identity checks proving one of
these two independent shapes:

- an assistant message routed through provider `openai` with non-empty message
  and session IDs;
- `parts[index]` is a tool part with non-empty tool, call, part, message, and
  session IDs, and the part references match the containing message;
- the tool state is `completed`, has an own time record, and has not been
  compacted; and
- `state.attachments[index]` is an own file attachment with non-empty IDs and an
  exact `data:<mime>;base64,<payload>` URL whose header MIME equals the declared
  attachment MIME.

Or:

- a user message has non-empty message and session IDs; and
- `parts[index]` is an own direct `file` part with a non-empty part ID, exact
  message/session references, and an exact `data:<mime>;base64,<payload>` URL
  whose header MIME equals the declared attachment MIME.

The only allowed MIME values are `image/png`, `image/jpeg`, and
`application/pdf`. Parameters, aliases such as `image/jpg`, unknown MIME values,
header mismatches, empty payloads, URL-safe Base64, malformed padding, and
noncanonical encodings fail closed. PNG additionally requires the reviewed
structural container validation. JPEG and PDF receive transport validation only;
the gateway does not claim their bytes form a semantically valid image or
document.

OpenCode import and fork remap the containing message and tool-part references
but can retain source IDs inside nested tool attachments. The reviewed converter
does not use those nested IDs for dispatch, so they must be present but need not
equal the remapped message. Direct user-file references must match their
containing message exactly. All other container identities are checked exactly.
Proxies, custom prototypes, accessors, non-enumerable or inherited qualifiers,
malformed shapes, compacted tool states, unsupported media, and aliases reached
through an unqualified path fail closed.

The transport validator caps the complete URL at `16,777,216` characters and
decoded bytes at `12,582,912`. It requires canonical standard Base64 and exact
round-trip encoding. PNG validation additionally caps chunks at `16,384`, each
dimension at `32,768`, and total pixels at `100,000,000`; it checks signature,
chunk boundaries, CRCs, IHDR and PLTE controls, contiguous IDAT chunks, known
critical chunks, and one final IEND with no trailing bytes. It validates a PNG
container, not decompressed pixels or image meaning. OCR-visible secrets,
steganography, malware, decoded-content DLP, and authenticated attachment origin
remain outside this regex DLP guarantee.

This path is pinned to OpenCode `1.18.18` and its reviewed `message-v2.ts`
converter above. Its root catalog retains `ai` `6.0.168`, and
`packages/opencode/package.json` retains `@ai-sdk/openai` `3.0.84`. The reviewed
`ai` media mapping is `packages/ai/src/prompt/convert-to-language-model-prompt.ts`
at commit `c38119a2e3df201a95a9979580f2c7a3c1b319ab`, blob
`4fedd90b17f82c24cff7fd41b7f4872412a8a7d0`; it maps direct user and tool-result
`image/*` data to image content and other media to file content. The reviewed
Responses converter is
`packages/openai/src/responses/convert-to-openai-responses-input.ts` at commit
`da385f747e8277411d8b49c65e8a22c3bf158f4c`. It serializes JPEG and PNG as
`input_image` and PDF as `input_file` for direct user content and inside
`function_call_output.output`. Converter drift must fail closed until all three
layers are reverified.

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
text, preserved ciphertext, and qualified attachment URLs. Local UI-only tool
metadata is not traversed or charged because the reviewed converter does not
dispatch it. Public `scannedChars` telemetry counts each qualified URL once
because every configured detector except the one transport-incompatible Google
detector still checks it. Provider traversal revisits shared objects at each
path, so a
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
- a frozen six-default-detector compatibility manifest with mutation
  sensitivity, synthetic matching samples, and an ordinary task-path negative
  regression for the left-token-bounded `sk-` detector;
- canonical PNG, JPEG, and PDF collision, provenance, MIME/header, payload-range,
  alias, parser, resource, and performance boundary tests, including exact
  overrides, duplicate/equivalent detectors, and other custom detectors that
  must still block;
- alias, cycle, depth, proxy/callable, custom/prototype-polluted, accessor,
  non-enumerable, symbol, sparse/extended-array, malformed-primitive,
  malformed-property, and unknown-field tests;
- assembled-plugin default-versus-legacy resume regression tests;
- gateway lint, build, full tests, and provider-boundary live smoke;
- credential-free `make gateway-resume-redaction-e2e`, which imports a private
  synthetic large session, forks it through OpenCode `1.18.18`, and requires
  native OpenAI localhost dispatch with absent-item-ID ciphertext, redaction,
  metadata projection, exact direct-user and tool-result PNG/JPEG `input_image`
  entries, direct-user and tool-result PDF `input_file` entries, source-integrity,
  audit, and cleanup assertions;
- static release-contract coverage proving `release-check` depends on the
  unsuppressed native resume gate; and
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
