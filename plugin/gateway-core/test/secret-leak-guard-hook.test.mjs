import assert from "node:assert/strict"
import { mkdtempSync, readFileSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"
import { createSecretRedactor } from "../dist/hooks/shared/secret-redaction.js"
import {
  attachmentCollisionFixtures,
  collisionBase64Payload,
  collisionPngBuffer,
  GOOGLE_KEY_COLLISION,
  pngDataUrl,
} from "./fixtures/provider-boundary-fixtures.mjs"

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

const GOOGLE_KEY_PATTERN = "AIza[0-9A-Za-z\\-_]{20,}"

function pngCollisionDataUrl() {
  const url = pngDataUrl(collisionPngBuffer())
  assert.equal(url.includes(GOOGLE_KEY_COLLISION), true)
  return url
}

function attachmentRedactor({
  patterns = [GOOGLE_KEY_PATTERN],
  omittablePatternIndex = 0,
  limits = {},
  providerLimits = {},
} = {}) {
  return createSecretRedactor({
    patterns,
    omittableOpaqueAttachmentPatternIndex: omittablePatternIndex,
    redactionToken: "[REDACTED]",
    limits: {
      maxDepth: 12,
      maxNodes: 20_000,
      maxChars: 2_097_152,
      ...limits,
    },
    providerLimits: {
      maxMessages: 20_000,
      maxNodes: 1_000_000,
      maxChars: 134_217_728,
      maxMessageChars: 16_777_216,
      ...providerLimits,
    },
  })
}

function jsonStringChars(value) {
  if (typeof value === "string") return value.length
  if (Array.isArray(value)) {
    return value.reduce((total, child) => total + jsonStringChars(child), 0)
  }
  if (!value || typeof value !== "object") return 0
  return Object.entries(value).reduce(
    (total, [key, child]) => total + key.length + jsonStringChars(child),
    0,
  )
}

function pngAttachmentMessage(url = pngCollisionDataUrl()) {
  const sessionID = "ses_png_attachment"
  const messageID = "msg_png_attachment"
  return {
    info: {
      id: messageID,
      sessionID,
      role: "assistant",
      providerID: "openai",
      modelID: "gpt-5.6-sol",
    },
    parts: [
      {
        id: "prt_png_tool",
        sessionID,
        messageID,
        type: "tool",
        tool: "read",
        callID: "call_png_attachment",
        state: {
          status: "completed",
          input: { filePath: "/tmp/screenshot.png" },
          output: "token=MutablePngSiblingSecret_123456",
          time: { start: 1, end: 2 },
          attachments: [
            {
              id: "prt_png_file",
              sessionID,
              messageID,
              type: "file",
              mime: "image/png",
              url,
            },
          ],
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

test("assembled provider finalizer accepts the resumed-history regression fixture with defaults", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-secret-resume-defaults-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: { enabled: false, order: [], disabled: ["secret-leak-guard"] },
      },
    })
    const ciphertext = `${"A".repeat(128)}-sk-opaque-ciphertext-collision-1234567890`
    const uiOnlyMetadata = {
      files: [{ patch: "sk-ui-only-patch-collision-1234567890" }],
      preview: "token=UiOnlyPreviewSecret_123456",
    }
    const largeHistory = `resume-history-control:${"H".repeat(2_097_152)}`
    const messages = [
      {
        info: { role: "user", sessionID: "session-resume-regression" },
        parts: [{ type: "text", text: largeHistory }],
      },
      reasoningMessage(ciphertext),
      {
        info: {
          role: "assistant",
          providerID: "openai",
          sessionID: "session-resume-regression",
        },
        parts: [
          {
            type: "tool",
            tool: "bash",
            callID: "call-resume-regression",
            state: {
              status: "completed",
              input: { command: "safe" },
              output: "safe",
              metadata: uiOnlyMetadata,
            },
          },
        ],
      },
    ]

    await plugin["experimental.chat.messages.transform"]({}, { messages })

    assert.equal(messages[0].parts[0].text, largeHistory)
    assert.equal(
      messages[1].parts[0].metadata.openai.reasoningEncryptedContent,
      ciphertext,
    )
    assert.equal(messages[1].parts[0].text, "[REDACTED_SECRET]")
    assert.equal(messages[2].parts[0].state.metadata, uiOnlyMetadata)
    assert.equal(
      uiOnlyMetadata.files[0].patch,
      "sk-ui-only-patch-collision-1234567890",
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("assembled provider finalizer keeps explicit legacy history limits fail closed", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-secret-resume-legacy-"))
  try {
    const plugin = pluginFor(directory, {
      hooks: { enabled: false, order: [], disabled: ["secret-leak-guard"] },
    })
    const messages = [
      {
        info: { role: "user", sessionID: "session-resume-legacy" },
        parts: [{ type: "text", text: "H".repeat(2_097_153) }],
      },
    ]

    await assert.rejects(
      plugin["experimental.chat.messages.transform"]({}, { messages }),
      /text_limit/,
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

test("provider session audit fallback never invokes message accessors or proxies", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-secret-session-fallback-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: { hooks: { enabled: false, order: [], disabled: [] } },
    })
    let accessorCalls = 0
    const accessorMessage = {}
    Object.defineProperty(accessorMessage, "info", {
      enumerable: true,
      get: () => {
        accessorCalls += 1
        throw new Error("message info accessor invoked")
      },
    })
    await assert.rejects(
      plugin["experimental.chat.messages.transform"]({}, { messages: [accessorMessage] }),
      (error) => error.code === "malformed_provider_object",
    )
    assert.equal(accessorCalls, 0)

    let proxyTrapCalls = 0
    const proxyInfo = new Proxy(
      {},
      {
        getOwnPropertyDescriptor: () => {
          proxyTrapCalls += 1
          throw new Error("message info proxy trap invoked")
        },
      },
    )
    await assert.rejects(
      plugin["experimental.chat.messages.transform"](
        {},
        { messages: [{ info: proxyInfo }] },
      ),
      (error) => error.code === "malformed_provider_object",
    )
    assert.equal(proxyTrapCalls, 0)
  } finally {
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

test("provider redactor preserves a canonical PNG Google-key collision and scans siblings", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-secret-png-attachment-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: { hooks: { enabled: false, order: [], disabled: [] } },
    })
    const message = pngAttachmentMessage()
    const originalUrl = message.parts[0].state.attachments[0].url

    await plugin["experimental.chat.messages.transform"]({}, { messages: [message] })

    assert.equal(message.parts[0].state.attachments[0].url, originalUrl)
    assert.equal(message.parts[0].state.output, "[REDACTED_SECRET]")

    const wrongMime = pngAttachmentMessage()
    wrongMime.parts[0].state.attachments[0].mime = "image/jpeg"
    await assert.rejects(
      plugin["experimental.chat.messages.transform"]({}, { messages: [wrongMime] }),
      (error) => {
        assert.equal(error.code, "immutable_match")
        assert.equal(error.patternIndex, 3)
        assert.equal(error.locationCode, "immutable_protocol_field")
        return true
      },
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("provider attachment exception is unavailable to an exact configured pattern override", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-secret-png-custom-pattern-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: { enabled: false, order: [], disabled: [] },
        secretLeakGuard: {
          patterns: ["AIza[0-9A-Za-z\\-_]{20,}"],
        },
      },
    })
    await assert.rejects(
      plugin["experimental.chat.messages.transform"](
        {},
        { messages: [pngAttachmentMessage()] },
      ),
      (error) => {
        assert.equal(error.code, "immutable_match")
        assert.equal(error.patternIndex, 0)
        return true
      },
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("provider attachment exception omits only the built-in Google detector", () => {
  const message = pngAttachmentMessage()
  const redactor = attachmentRedactor({
    patterns: [GOOGLE_KEY_PATTERN, "iVBORw0KGgo[A-Za-z0-9+/=]{10,}"],
  })

  assert.throws(
    () => redactor.redactProviderMessages([message]),
    (error) => {
      assert.equal(error.code, "immutable_match")
      assert.equal(error.patternIndex, 1)
      return true
    },
  )
})

test("provider attachment exception fails closed for wrong provenance and malformed envelopes", () => {
  const url = pngCollisionDataUrl()
  const variants = []
  const addVariant = (mutate) => {
    const message = pngAttachmentMessage(url)
    mutate(message)
    variants.push(message)
  }
  addVariant((message) => {
    message.info.role = "user"
  })
  addVariant((message) => {
    message.info.providerID = "anthropic"
  })
  addVariant((message) => {
    message.parts[0].state.status = "error"
  })
  addVariant((message) => {
    delete message.parts[0].tool
  })
  addVariant((message) => {
    delete message.parts[0].callID
  })
  addVariant((message) => {
    delete message.parts[0].id
  })
  addVariant((message) => {
    message.parts[0].sessionID = "ses_other"
  })
  addVariant((message) => {
    delete message.parts[0].state.time
  })
  addVariant((message) => {
    message.parts[0].state.time.compacted = 3
  })
  addVariant((message) => {
    message.parts[0].state.attachments[0].type = "future-file"
  })
  addVariant((message) => {
    message.parts[0].state.attachments[0].mime = "image/jpeg"
  })
  addVariant((message) => {
    delete message.info.id
  })
  addVariant((message) => {
    message.parts[0].messageID = "msg_other"
  })
  addVariant((message) => {
    delete message.parts[0].state.attachments[0].id
  })
  addVariant((message) => {
    delete message.parts[0].state.attachments[0].messageID
  })
  addVariant((message) => {
    delete message.parts[0].state.attachments[0].sessionID
  })
  addVariant((message) => {
    message.parts[0].state.attachments[0].url = `${url}AAAA`
  })
  for (const message of variants) {
    const redactor = attachmentRedactor()
    assert.throws(
      () => redactor.redactProviderMessages([message]),
      (error) => {
        assert.equal(error.code, "immutable_match")
        assert.equal(error.patternIndex, 0)
        return true
      },
    )
  }
})

test("provider traversal rejects exotic property graphs without invoking accessors", () => {
  const url = pngCollisionDataUrl()
  let getterCalls = 0
  const variants = []

  {
    const message = pngAttachmentMessage(url)
    const attachment = message.parts[0].state.attachments[0]
    const inherited = Object.assign(Object.create({ url }), attachment)
    delete inherited.url
    message.parts[0].state.attachments[0] = inherited
    variants.push(message)
  }
  {
    const message = pngAttachmentMessage(url)
    Object.defineProperty(message.parts[0].state.attachments[0], "url", {
      configurable: true,
      enumerable: false,
      value: url,
      writable: true,
    })
    variants.push(message)
  }
  {
    const message = pngAttachmentMessage(url)
    const attachment = message.parts[0].state.attachments[0]
    delete attachment.url
    Object.defineProperty(attachment, "url", {
      configurable: true,
      enumerable: true,
      get: () => {
        getterCalls += 1
        return getterCalls === 1 ? "safe" : url
      },
    })
    variants.push(message)
  }
  {
    const message = pngAttachmentMessage(url)
    message.parts[0].state.attachments[0] = new Proxy(
      message.parts[0].state.attachments[0],
      {},
    )
    variants.push(message)
  }
  {
    const message = pngAttachmentMessage(url)
    message.parts[0].state.attachments[0][Symbol("hidden")] = "safe"
    variants.push(message)
  }
  {
    const message = pngAttachmentMessage(url)
    message.parts[0].state.attachments.extra = "safe"
    variants.push(message)
  }
  {
    const message = pngAttachmentMessage(url)
    message.parts[0].state.attachments[0] = Object.assign(
      () => undefined,
      message.parts[0].state.attachments[0],
    )
    variants.push(message)
  }
  {
    const source = pngAttachmentMessage(url)
    variants.push(Object.assign(() => undefined, source))
  }
  {
    const message = pngAttachmentMessage(url)
    message.parts[0].state = Object.assign(() => undefined, message.parts[0].state)
    variants.push(message)
  }
  {
    const message = pngAttachmentMessage(url)
    message.parts[0].state.status = "error"
    message.parts[0].state.attachments = []
    message.parts[0].state.metadata = Object.assign(() => undefined, {
      interrupted: true,
      output: url,
    })
    variants.push(message)
  }
  {
    const message = pngAttachmentMessage(url)
    const callable = Object.assign(
      () => undefined,
      message.parts[0].state.attachments[0],
    )
    message.parts[0].state.attachments[0] = new Proxy(callable, {})
    variants.push(message)
  }

  for (const [variantIndex, message] of variants.entries()) {
    const redactor = attachmentRedactor()
    assert.throws(
      () => redactor.redactProviderMessages([message]),
      (error) => {
        assert.equal(error.code, "malformed_provider_object", `variant ${variantIndex}`)
        return true
      },
    )
  }
  const sparseMessages = new Array(1)
  for (const malformedMessages of [
    sparseMessages,
    [undefined],
    [Symbol("provider-value")],
    [1n],
    [Number.NaN],
    [Number.POSITIVE_INFINITY],
  ]) {
    assert.throws(
      () =>
        attachmentRedactor().redactProviderMessages(malformedMessages),
      (error) => error.code === "malformed_provider_object",
    )
  }

  Object.defineProperty(Object.prototype, "url", {
    configurable: true,
    enumerable: false,
    value: url,
  })
  try {
    assert.throws(
      () =>
        attachmentRedactor().redactProviderMessages([pngAttachmentMessage(url)]),
      (error) => error.code === "malformed_provider_object",
    )
  } finally {
    delete Object.prototype.url
  }
  assert.equal(getterCalls, 0)
})

test("provider attachment exception requires one explicitly designated default detector", () => {
  const options = {
    redactionToken: "[REDACTED]",
    limits: { maxDepth: 12, maxNodes: 20_000, maxChars: 2_097_152 },
    providerLimits: {
      maxMessages: 20_000,
      maxNodes: 1_000_000,
      maxChars: 134_217_728,
      maxMessageChars: 16_777_216,
    },
  }
  const exactPattern = "AIza[0-9A-Za-z\\-_]{20,}"

  assert.throws(
    () =>
      createSecretRedactor({ patterns: [exactPattern], ...options }).redactProviderMessages([
        pngAttachmentMessage(),
      ]),
    (error) => {
      assert.equal(error.code, "immutable_match")
      assert.equal(error.patternIndex, 0)
      return true
    },
  )

  assert.throws(
    () =>
      createSecretRedactor({
        patterns: [exactPattern, exactPattern],
        omittableOpaqueAttachmentPatternIndex: 0,
        ...options,
      }).redactProviderMessages([pngAttachmentMessage()]),
    (error) => {
      assert.equal(error.code, "immutable_match")
      assert.equal(error.patternIndex, 1)
      return true
    },
  )

  assert.throws(
    () =>
      createSecretRedactor({
        patterns: [`(?i)${exactPattern}`],
        omittableOpaqueAttachmentPatternIndex: 0,
        ...options,
      }).redactProviderMessages([pngAttachmentMessage()]),
    (error) => {
      assert.equal(error.code, "immutable_match")
      assert.equal(error.patternIndex, 0)
      return true
    },
  )

  assert.throws(
    () =>
      createSecretRedactor({
        patterns: ["AIza[0-9A-Za-z_-]{20,}"],
        omittableOpaqueAttachmentPatternIndex: 0,
        ...options,
      }).redactProviderMessages([pngAttachmentMessage()]),
    (error) => {
      assert.equal(error.code, "immutable_match")
      assert.equal(error.patternIndex, 0)
      return true
    },
  )
})

test("provider attachment exception tolerates stale nested references after import and fork", () => {
  const message = pngAttachmentMessage()
  message.parts[0].state.attachments[0].messageID = "msg_source_before_fork"
  message.parts[0].state.attachments[0].sessionID = "ses_source_before_fork"

  const redactor = attachmentRedactor()

  assert.doesNotThrow(() => redactor.redactProviderMessages([message]))
})

test("provider attachment exception revisits trusted attachment aliases through untrusted paths", () => {
  for (const trustedFirst of [true, false]) {
    const base = pngAttachmentMessage()
    const alias = base.parts[0].state.attachments[0]
    const message = trustedFirst
      ? { ...base, future: alias }
      : { future: alias, ...base }
    const redactor = attachmentRedactor()
    assert.throws(
      () => redactor.redactProviderMessages([message]),
      (error) => {
        assert.equal(error.code, "immutable_match")
        assert.equal(error.patternIndex, 0)
        return true
      },
    )
  }
})

test("provider attachment accounting charges each envelope exactly once", () => {
  const shortFixture = attachmentCollisionFixtures().find(
    (fixture) => fixture.mime === "application/pdf",
  )
  assert.ok(shortFixture)
  const longPayload = collisionBase64Payload(
    Buffer.from("%PDF-1.7\n", "ascii"),
    Buffer.concat([Buffer.from("\n%%EOF\n", "ascii"), Buffer.alloc(3)]),
  )
  const longFixture = {
    ...shortFixture,
    url: `data:application/pdf;base64,${longPayload}`,
  }
  assert.equal(longFixture.url.length - shortFixture.url.length, 4)

  const messageFor = (fixture) => {
    const message = pngAttachmentMessage(fixture.url)
    message.parts[0].state.attachments[0].mime = fixture.mime
    return message
  }
  const cases = [shortFixture, longFixture].map((fixture) => {
    const message = messageFor(fixture)
    return { fixture, expectedChars: jsonStringChars(message) }
  })
  assert.equal(cases[1].expectedChars - cases[0].expectedChars, 4)

  for (const { fixture, expectedChars } of cases) {
    const exactStats = attachmentRedactor({
      providerLimits: {
        maxChars: expectedChars,
        maxMessageChars: expectedChars,
      },
    }).redactProviderMessages([messageFor(fixture)])
    assert.equal(exactStats.scannedChars, expectedChars)
    assert.equal(exactStats.omittedOpaqueAttachmentMatches, 1)
    assert.equal(exactStats.matches, 0)

    for (const constrainedLimit of ["maxChars", "maxMessageChars"]) {
      assert.throws(
        () =>
          attachmentRedactor({
            providerLimits: {
              maxChars: expectedChars,
              maxMessageChars: expectedChars,
              [constrainedLimit]: expectedChars - 1,
            },
          }).redactProviderMessages([messageFor(fixture)]),
        (error) => error.code === "text_limit",
      )
    }
  }
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

  for (const [message, expectedCode] of [
    [errorMessage(inheritedInterrupted), "malformed_provider_object"],
    [errorMessage(accessorInterrupted), "malformed_provider_object"],
    [errorMessage(accessorOutput), "malformed_provider_object"],
    [
      errorMessage({ interrupted: true, output: { text: "safe" } }),
      "malformed_provider_metadata",
    ],
    [errorMessage({ preview: "safe" }, "future-status"), "malformed_provider_metadata"],
  ]) {
    assert.throws(
      () => directRedactor().redactProviderMessages([message]),
      (error) => error.code === expectedCode,
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

  const nullItem = reasoningMessage(ciphertext)
  nullItem.parts[0].metadata.openai.itemId = null
  cases.push(nullItem)

  const emptyItem = reasoningMessage(ciphertext)
  emptyItem.parts[0].metadata.openai.itemId = ""
  cases.push(emptyItem)

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

  for (const [index, message] of cases.entries()) {
    assert.throws(
      () => directRedactor().redactProviderMessages([message]),
      (error) =>
        error.code === (index < cases.length - 2 ? "immutable_match" : "malformed_provider_object"),
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

test("provider depth limit accepts the exact boundary and rejects one level over", () => {
  const redactor = directRedactor({ limits: { maxDepth: 2 } })
  assert.doesNotThrow(() => redactor.redactProviderMessages([{ future: "safe" }]))
  assert.throws(
    () => redactor.redactProviderMessages([{ future: { text: "safe" } }]),
    (error) => error.code === "depth_limit",
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
    omittedOpaqueAttachmentMatches: 0,
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
