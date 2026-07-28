import assert from "node:assert/strict"
import { mkdtempSync, readFileSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"
import { createSecretRedactor } from "../dist/hooks/shared/secret-redaction.js"

function secretConfig(overrides = {}) {
  return {
    enabled: true,
    providerBoundaryEnabled: true,
    redactionToken: "[REDACTED]",
    patterns: [
      "sk-[A-Za-z0-9_\\-]{10,}",
      "(?i)(api[_-]?key|token|secret|password)\\s*[:=]\\s*[A-Za-z0-9_\\-]{12,}",
    ],
    maxDepth: 12,
    maxNodes: 20000,
    maxChars: 2097152,
    ...overrides,
  }
}

function pluginFor(directory, config = {}) {
  return GatewayCorePlugin({
    directory,
    config: {
      hooks: { enabled: true, order: ["secret-leak-guard"], disabled: [] },
      secretLeakGuard: secretConfig(),
      ...config,
    },
  })
}

function directRedactor({ limits = {}, providerLimits = {} } = {}) {
  return createSecretRedactor({
    patterns: secretConfig().patterns,
    redactionToken: "[REDACTED]",
    limits: {
      maxDepth: 12,
      maxNodes: 20000,
      maxChars: 2097152,
      ...limits,
    },
    providerLimits: {
      maxMessages: 20000,
      maxNodes: 1000000,
      maxChars: 134217728,
      maxMessageChars: 16777216,
      ...providerLimits,
    },
  })
}

function reasoningMessage(ciphertext) {
  return {
    info: { role: "assistant", providerID: "openai" },
    parts: [
      {
        type: "reasoning",
        text: "token=MutableReasoningSecret_123456",
        metadata: {
          openai: {
            itemId: "rs_0123456789abcdef",
            reasoningEncryptedContent: ciphertext,
          },
        },
      },
    ],
  }
}

test("secret-leak-guard redacts all structured tool output channels", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-secret-guard-"))
  try {
    const plugin = pluginFor(directory)
    const output = {
      output: {
        stdout: "API_KEY=UpperCaseSecret_123456",
        output: "token=OutputSecret_123456",
        message: "password=MessageSecret_123456",
        stderr: "sk-modern-key-with-hyphens_1234567890",
        nested: { authorization: "token=NestedSecret_123456" },
      },
    }
    await plugin["tool.execute.after"](
      { tool: "bash", sessionID: "session-secret" },
      output,
    )
    const serialized = JSON.stringify(output.output)
    assert.equal(serialized.includes("Secret_123456"), false)
    assert.equal(serialized.includes("sk-modern-key"), false)
    assert.equal(serialized.includes("[REDACTED]"), true)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("default case-insensitive assignment pattern is active", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-secret-default-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: { enabled: true, order: ["secret-leak-guard"], disabled: [] },
      },
    })
    const output = { output: "API_KEY=DefaultPatternSecret_123456" }
    await plugin["tool.execute.after"]({ tool: "bash" }, output)
    assert.equal(output.output.includes("DefaultPatternSecret_123456"), false)
    assert.equal(output.output.includes("[REDACTED_SECRET]"), true)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("malformed secret patterns fail closed without exposing pattern text", () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-secret-invalid-"))
  try {
    assert.throws(
      () =>
        GatewayCorePlugin({
          directory,
          config: {
            secretLeakGuard: secretConfig({ patterns: ["SENSITIVE_PATTERN("] }),
          },
        }),
      (error) => {
        assert.match(String(error), /invalid_pattern/)
        assert.match(String(error), /index=0/)
        assert.doesNotMatch(String(error), /SENSITIVE_PATTERN/)
        return true
      },
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("provider finalizer redacts runtime-shaped mutable content and preserves protocol fields", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-secret-provider-"))
  try {
    const plugin = pluginFor(directory, {
      hooks: { enabled: false, order: [], disabled: ["secret-leak-guard"] },
    })
    const messages = [
      {
        info: {
          id: "msg-safe-id",
          sessionID: "session-provider",
          role: "user",
          system: ["password=SystemSecret_123456"],
          summary: { title: "token=SummarySecret_123456" },
          metadata: { trace: "safe-trace" },
        },
        parts: [
          { type: "text", text: "api_key=TextSecret_123456" },
          {
            type: "reasoning",
            text: "secret=ReasoningSecret_123456",
            metadata: {
              openai: {
                itemId: "fc_0123456789abcdef0123456789abcdef0123456789abcdef",
              },
            },
          },
          {
            type: "tool",
            tool: "bash",
            callID: "call-safe-id",
            state: {
              status: "completed",
              input: { command: "echo token=InputSecret_123456" },
              output: "password=ToolOutputSecret_123456",
              title: "secret=ToolTitleSecret_123456",
              metadata: { trace: "safe-tool-trace" },
            },
          },
          {
            type: "file",
            url: "https://example.invalid/safe",
            source: { text: "api_key=SourceSecret_123456" },
          },
        ],
      },
    ]

    await plugin["experimental.chat.messages.transform"]({}, { messages })
    const serialized = JSON.stringify(messages)
    assert.equal(serialized.includes("Secret_123456"), false)
    assert.equal(serialized.includes("[REDACTED]"), true)
    assert.equal(messages[0].info.id, "msg-safe-id")
    assert.equal(messages[0].info.role, "user")
    assert.equal(messages[0].parts[2].tool, "bash")
    assert.equal(messages[0].parts[2].callID, "call-safe-id")
    assert.equal(messages[0].parts[3].url, "https://example.invalid/safe")
    assert.equal(messages[0].info.metadata.trace, "safe-trace")
    assert.equal(
      messages[0].parts[1].metadata.openai.itemId,
      "fc_0123456789abcdef0123456789abcdef0123456789abcdef",
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("provider finalizer redacts system context after generic hooks are disabled", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-secret-system-"))
  try {
    const plugin = pluginFor(directory, {
      hooks: { enabled: false, order: [], disabled: [] },
    })
    const output = { system: ["token=SystemBoundarySecret_123456"] }
    await plugin["experimental.chat.system.transform"](
      { sessionID: "system-session" },
      output,
    )
    assert.equal(output.system[0], "[REDACTED]")
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("explicit provider-boundary opt-out leaves transform content unchanged", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-secret-optout-"))
  try {
    const plugin = pluginFor(directory, {
      secretLeakGuard: secretConfig({ providerBoundaryEnabled: false }),
    })
    const messages = [
      { info: { role: "user" }, parts: [{ type: "text", text: "token=OptOutSecret_123456" }] },
    ]
    await plugin["experimental.chat.messages.transform"]({}, { messages })
    assert.equal(messages[0].parts[0].text, "token=OptOutSecret_123456")
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("immutable and unknown provider fields block without leaking canaries to audit", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-secret-block-"))
  const auditPath = join(directory, "gateway-events.jsonl")
  const previousAudit = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
  const previousPath = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT_PATH
  process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = "1"
  process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT_PATH = auditPath
  try {
    const plugin = pluginFor(directory)
    const canary = "UrlSecret_123456"
    const messages = [
      {
        info: { role: "user" },
        parts: [{ type: "file", url: `https://example.invalid/?token=${canary}` }],
      },
    ]
    await assert.rejects(
      plugin["experimental.chat.messages.transform"]({}, { messages }),
      /immutable_match/,
    )
    const audit = readFileSync(auditPath, "utf8")
    assert.match(audit, /provider_boundary_secret_dispatch_blocked/)
    assert.doesNotMatch(audit, new RegExp(canary))
    const urlBlock = JSON.parse(audit.trim().split("\n").at(-1))
    assert.equal(urlBlock.match_target, "value")
    assert.equal(urlBlock.pattern_index, 1)
    assert.equal(urlBlock.location_code, "immutable_protocol_field")

    const unknown = [
      {
        info: { role: "user" },
        parts: [{ type: "future-part", opaque: "secret=UnknownSecret_123456" }],
      },
    ]
    await assert.rejects(
      plugin["experimental.chat.messages.transform"]({}, { messages: unknown }),
      /immutable_match/,
    )
  } finally {
    if (previousAudit === undefined) delete process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
    else process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = previousAudit
    if (previousPath === undefined) delete process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT_PATH
    else process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT_PATH = previousPath
    rmSync(directory, { recursive: true, force: true })
  }
})

test("provider block diagnostics expose only allowlisted structural fields", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-secret-diagnostics-"))
  const auditPath = join(directory, "gateway-events.jsonl")
  const previousAudit = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
  const previousPath = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT_PATH
  process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = "1"
  process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT_PATH = auditPath
  try {
    const plugin = pluginFor(directory)
    const valueCanary = "sk-provider-metadata-canary-1234567890"
    const valueMessages = [
      {
        info: { role: "assistant" },
        parts: [
          {
            type: "reasoning",
            metadata: { openai: { encryptedContent: valueCanary } },
          },
        ],
      },
    ]
    await assert.rejects(
      plugin["experimental.chat.messages.transform"]({}, { messages: valueMessages }),
      (error) => {
        assert.equal(error.code, "immutable_match")
        assert.equal(error.matchTarget, "value")
        assert.equal(error.patternIndex, 0)
        assert.equal(error.locationCode, "provider_metadata_openai_other")
        assert.doesNotMatch(String(error), new RegExp(valueCanary))
        return true
      },
    )

    const keyCanary = "token=ProviderKeyCanary_123456"
    const keyMessages = [
      {
        info: { role: "assistant" },
        parts: [{ type: "future-part", [keyCanary]: "safe" }],
      },
    ]
    await assert.rejects(
      plugin["experimental.chat.messages.transform"]({}, { messages: keyMessages }),
      (error) => {
        assert.equal(error.code, "immutable_match")
        assert.equal(error.matchTarget, "key")
        assert.equal(error.patternIndex, 1)
        assert.equal(error.locationCode, "unknown_field")
        assert.doesNotMatch(String(error), new RegExp(keyCanary))
        return true
      },
    )

    const audit = readFileSync(auditPath, "utf8")
    const rows = audit
      .trim()
      .split("\n")
      .map((line) => JSON.parse(line))
      .filter((row) => row.reason_code === "provider_boundary_secret_dispatch_blocked")
    assert.deepEqual(
      rows.map((row) => ({
        match_target: row.match_target,
        pattern_index: row.pattern_index,
        location_code: row.location_code,
      })),
      [
        {
          match_target: "value",
          pattern_index: 0,
          location_code: "provider_metadata_openai_other",
        },
        {
          match_target: "key",
          pattern_index: 1,
          location_code: "unknown_field",
        },
      ],
    )
    assert.doesNotMatch(audit, new RegExp(valueCanary))
    assert.doesNotMatch(audit, new RegExp(keyCanary))
    assert.doesNotMatch(audit, /sk-\[A-Za-z/)
  } finally {
    if (previousAudit === undefined) delete process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
    else process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = previousAudit
    if (previousPath === undefined) delete process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT_PATH
    else process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT_PATH = previousPath
    rmSync(directory, { recursive: true, force: true })
  }
})

test("provider redactor preserves exact OpenAI reasoning ciphertext and scans siblings", () => {
  const ciphertext = `${"A".repeat(4000)}sk-ciphertext-collision-1234567890`
  const message = reasoningMessage(ciphertext)
  const stats = directRedactor().redactProviderMessages([message])

  assert.equal(message.parts[0].metadata.openai.reasoningEncryptedContent, ciphertext)
  assert.equal(message.parts[0].text, "[REDACTED]")
  assert.equal(stats.matches, 1)
  assert.equal(stats.redactedFields, 1)
  assert.equal(stats.scannedChars < ciphertext.length, true)
  assert.equal(stats.scannedNodes > 1, true)
})

test("provider redactor projects only tool state metadata that OpenCode dispatches", () => {
  const completedMetadata = {
    files: [{ patch: "sk-internal-patch-secret-1234567890" }],
    display: { path: "token=InternalDisplaySecret_123456" },
    preview: "password=InternalPreviewSecret_123456",
  }
  const completed = {
    info: { role: "assistant", providerID: "openai" },
    parts: [
      {
        type: "tool",
        tool: "bash",
        callID: "call-safe",
        state: {
          status: "completed",
          input: { command: "token=ToolInputSecret_123456" },
          output: "password=ToolOutputSecret_123456",
          metadata: completedMetadata,
        },
      },
    ],
  }
  directRedactor().redactProviderMessages([completed])
  assert.equal(completed.parts[0].state.input.command, "[REDACTED]")
  assert.equal(completed.parts[0].state.output, "[REDACTED]")
  assert.equal(completed.parts[0].state.metadata, completedMetadata)
  assert.equal(completedMetadata.files[0].patch, "sk-internal-patch-secret-1234567890")
  assert.equal(completedMetadata.preview, "password=InternalPreviewSecret_123456")

  const interrupted = {
    info: { role: "assistant", providerID: "openai" },
    parts: [
      {
        type: "tool",
        tool: "bash",
        callID: "call-interrupted",
        state: {
          status: "error",
          input: { command: "safe" },
          error: "secret=ToolErrorSecret_123456",
          metadata: {
            interrupted: true,
            output: "token=InterruptedOutputSecret_123456",
            preview: "sk-internal-preview-secret-1234567890",
          },
        },
      },
    ],
  }
  directRedactor().redactProviderMessages([interrupted])
  assert.equal(interrupted.parts[0].state.error, "[REDACTED]")
  assert.equal(interrupted.parts[0].state.metadata.output, "[REDACTED]")
  assert.equal(
    interrupted.parts[0].state.metadata.preview,
    "sk-internal-preview-secret-1234567890",
  )

  const missingInterruptedOutput = structuredClone(interrupted)
  missingInterruptedOutput.parts[0].state.error = "secret=MissingOutputErrorSecret_123456"
  missingInterruptedOutput.parts[0].state.metadata = { interrupted: true }
  directRedactor().redactProviderMessages([missingInterruptedOutput])
  assert.equal(missingInterruptedOutput.parts[0].state.error, "[REDACTED]")

  const notInterrupted = structuredClone(interrupted)
  notInterrupted.parts[0].state.metadata = {
    interrupted: false,
    output: "token=UndispatchedOutputSecret_123456",
  }
  directRedactor().redactProviderMessages([notInterrupted])
  assert.equal(
    notInterrupted.parts[0].state.metadata.output,
    "token=UndispatchedOutputSecret_123456",
  )
})

test("tool state metadata projection rejects malformed control properties", () => {
  function errorMessage(metadata, status = "error") {
    return {
      info: { role: "assistant", providerID: "openai" },
      parts: [
        {
          type: "tool",
          tool: "bash",
          callID: "call-error",
          state: { status, input: {}, error: "safe", metadata },
        },
      ],
    }
  }

  const inheritedInterrupted = Object.assign(Object.create({ interrupted: true }), {
    output: "token=InheritedControlSecret_123456",
  })
  const accessorInterrupted = { output: "token=AccessorControlSecret_123456" }
  Object.defineProperty(accessorInterrupted, "interrupted", {
    enumerable: true,
    get: () => true,
  })
  const accessorOutput = { interrupted: true }
  Object.defineProperty(accessorOutput, "output", {
    enumerable: true,
    get: () => "token=AccessorOutputSecret_123456",
  })

  for (const message of [
    errorMessage(inheritedInterrupted),
    errorMessage(accessorInterrupted),
    errorMessage(accessorOutput),
    errorMessage({ interrupted: true, output: { text: "safe" } }),
    errorMessage({ preview: "safe" }, "future-status"),
  ]) {
    assert.throws(
      () => directRedactor().redactProviderMessages([message]),
      (error) => error.code === "malformed_provider_metadata",
    )
  }
})

test("nondispatched tool metadata aliases remain scanned through dispatched paths", () => {
  for (const metadataFirst of [true, false]) {
    const shared = { preview: "token=AliasedMetadataSecret_123456" }
    const state = metadataFirst
      ? { status: "completed", metadata: shared, input: shared, output: "safe" }
      : { status: "completed", input: shared, output: "safe", metadata: shared }
    const message = {
      info: { role: "assistant", providerID: "openai" },
      parts: [{ type: "tool", tool: "bash", callID: "call-alias", state }],
    }
    directRedactor().redactProviderMessages([message])
    assert.equal(shared.preview, "[REDACTED]")
  }

  const providerMetadata = {
    info: { role: "assistant", providerID: "openai" },
    parts: [
      {
        type: "tool",
        tool: "bash",
        callID: "call-provider-metadata",
        metadata: { preview: "sk-provider-metadata-secret-1234567890" },
        state: { status: "completed", input: {}, output: "safe", metadata: {} },
      },
    ],
  }
  assert.throws(
    () => directRedactor().redactProviderMessages([providerMetadata]),
    (error) => error.code === "immutable_match",
  )
})

test("reasoning ciphertext exemption requires exact own provider provenance", () => {
  const ciphertext = "sk-provider-ciphertext-collision-1234567890"
  const cases = []

  const wrongRole = reasoningMessage(ciphertext)
  wrongRole.info.role = "user"
  cases.push(wrongRole)

  const wrongProvider = reasoningMessage(ciphertext)
  wrongProvider.info.providerID = "other"
  cases.push(wrongProvider)

  const wrongPart = reasoningMessage(ciphertext)
  wrongPart.parts[0].type = "text"
  cases.push(wrongPart)

  const wrongItem = reasoningMessage(ciphertext)
  wrongItem.parts[0].metadata.openai.itemId = "fc_0123456789abcdef"
  cases.push(wrongItem)

  const wrongKey = reasoningMessage(ciphertext)
  wrongKey.parts[0].metadata.openai.encryptedContent = ciphertext
  delete wrongKey.parts[0].metadata.openai.reasoningEncryptedContent
  cases.push(wrongKey)

  const inheritedRole = reasoningMessage(ciphertext)
  inheritedRole.info = Object.assign(Object.create({ role: "assistant" }), {
    providerID: "openai",
  })
  cases.push(inheritedRole)

  const accessorItem = reasoningMessage(ciphertext)
  Object.defineProperty(accessorItem.parts[0].metadata.openai, "itemId", {
    configurable: true,
    enumerable: true,
    get: () => "rs_0123456789abcdef",
  })
  cases.push(accessorItem)

  for (const message of cases) {
    assert.throws(
      () => directRedactor().redactProviderMessages([message]),
      (error) => error.code === "immutable_match",
    )
  }
})

test("provider traversal revisits qualified aliases under every current path", () => {
  const ciphertext = "sk-provider-ciphertext-collision-1234567890"
  for (const trustedFirst of [true, false]) {
    const trusted = reasoningMessage(ciphertext)
    trusted.parts[0].text = "safe"
    const shared = trusted.parts[0].metadata.openai
    const message = trustedFirst
      ? { ...trusted, shadow: { metadata: { openai: shared } } }
      : {
          info: trusted.info,
          shadow: { metadata: { openai: shared } },
          parts: trusted.parts,
        }
    assert.throws(
      () => directRedactor().redactProviderMessages([message]),
      (error) => error.code === "immutable_match",
    )
  }

  const trusted = reasoningMessage(ciphertext)
  trusted.parts[0].text = "safe"
  const shared = trusted.parts[0].metadata.openai
  const untrusted = {
    info: { role: "assistant", providerID: "openai" },
    parts: [{ type: "reasoning", metadata: { other: shared } }],
  }
  assert.throws(
    () => directRedactor().redactProviderMessages([trusted, untrusted]),
    (error) => error.code === "immutable_match",
  )
})

test("provider history limits are global, per-message, and exactly accounted", () => {
  const exact = directRedactor({
    limits: { maxNodes: 1, maxChars: 1 },
    providerLimits: {
      maxMessages: 2,
      maxNodes: 3,
      maxChars: 6,
      maxMessageChars: 3,
    },
  }).redactProviderMessages(["abc", "def"])
  assert.deepEqual(exact, {
    matches: 0,
    redactedFields: 0,
    scannedChars: 6,
    scannedNodes: 3,
  })

  for (const providerLimits of [
    { maxMessages: 1, maxNodes: 3, maxChars: 6, maxMessageChars: 3 },
    { maxMessages: 2, maxNodes: 2, maxChars: 6, maxMessageChars: 3 },
  ]) {
    assert.throws(
      () => directRedactor({ providerLimits }).redactProviderMessages(["abc", "def"]),
      (error) => error.code === "node_limit",
    )
  }
  for (const providerLimits of [
    { maxMessages: 2, maxNodes: 3, maxChars: 5, maxMessageChars: 3 },
    { maxMessages: 2, maxNodes: 3, maxChars: 6, maxMessageChars: 2 },
  ]) {
    assert.throws(
      () => directRedactor({ providerLimits }).redactProviderMessages(["abc", "def"]),
      (error) => error.code === "text_limit",
    )
  }

  const sparse = []
  sparse.length = 3
  assert.throws(
    () =>
      directRedactor({
        providerLimits: {
          maxMessages: 2,
          maxNodes: 100,
          maxChars: 100,
          maxMessageChars: 100,
        },
      }).redactProviderMessages(sparse),
    (error) => error.code === "node_limit",
  )
  assert.throws(
    () =>
      directRedactor({
        limits: { maxNodes: 1 },
        providerLimits: {
          maxMessages: 2,
          maxNodes: 100,
          maxChars: 100,
          maxMessageChars: 100,
        },
      }).redactProviderMessages([{ safe: "x" }]),
    (error) => error.code === "node_limit",
  )
})

test("qualified ciphertext charges bounded raw history budgets without regex scanning", () => {
  const first = reasoningMessage(`${"A".repeat(400)}sk-first-collision-1234567890`)
  const second = reasoningMessage(`${"B".repeat(400)}sk-second-collision-1234567890`)
  const stats = directRedactor({
    limits: { maxChars: 100 },
    providerLimits: {
      maxMessages: 2,
      maxNodes: 1000,
      maxChars: 2000,
      maxMessageChars: 800,
    },
  }).redactProviderMessages([first, second])
  assert.equal(stats.matches, 2)
  assert.equal(stats.redactedFields, 2)
  assert.equal(stats.scannedChars < 1000, true)

  assert.throws(
    () =>
      directRedactor({
        providerLimits: {
          maxMessages: 2,
          maxNodes: 1000,
          maxChars: 1000,
          maxMessageChars: 800,
        },
      }).redactProviderMessages([
        reasoningMessage(`${"A".repeat(400)}sk-first-collision-1234567890`),
        reasoningMessage(`${"B".repeat(400)}sk-second-collision-1234567890`),
      ]),
    (error) => error.code === "text_limit",
  )
  assert.throws(
    () =>
      directRedactor({
        providerLimits: {
          maxMessages: 1,
          maxNodes: 1000,
          maxChars: 2000,
          maxMessageChars: 500,
        },
      }).redactProviderMessages([
        reasoningMessage(`${"A".repeat(400)}sk-message-collision-1234567890`),
      ]),
    (error) => error.code === "text_limit",
  )
})

test("shared provider references remain valid while cycles and limits reject dispatch", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-secret-bounds-"))
  try {
    const plugin = pluginFor(directory)
    const sharedInput = { command: "token=SharedSecret_123456" }
    const sharedMessages = [
      {
        info: { role: "assistant" },
        parts: [
          { type: "tool", tool: "bash", state: { input: sharedInput } },
          { type: "tool", tool: "bash", state: { input: sharedInput } },
        ],
      },
    ]
    await plugin["experimental.chat.messages.transform"]({}, { messages: sharedMessages })
    assert.equal(sharedInput.command, "[REDACTED]")
    const cyclic = { type: "tool", state: { input: {} } }
    cyclic.state.input.self = cyclic
    const cycleMessages = [{ info: { role: "user" }, parts: [cyclic] }]
    await assert.rejects(
      plugin["experimental.chat.messages.transform"]({}, { messages: cycleMessages }),
      /cycle_detected/,
    )

    const limited = pluginFor(directory, {
      secretLeakGuard: secretConfig({ maxNodes: 2 }),
    })
    const messages = [{ info: { role: "user" }, parts: [{ type: "text", text: "safe" }] }]
    await assert.rejects(
      limited["experimental.chat.messages.transform"]({}, { messages }),
      /node_limit/,
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
