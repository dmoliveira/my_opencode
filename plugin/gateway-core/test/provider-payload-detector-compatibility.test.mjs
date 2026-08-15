import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import { DEFAULT_GATEWAY_CONFIG } from "../dist/config/schema.js"
import GatewayCorePlugin from "../dist/index.js"
import { createSecretRedactor } from "../dist/hooks/shared/secret-redaction.js"
import {
  attachmentCollisionFixtures,
  collisionBase64Payload,
  GOOGLE_KEY_COLLISION,
  pngDataUrl,
} from "./fixtures/provider-boundary-fixtures.mjs"

const DEFAULT_DETECTOR_MANIFEST = [
  {
    source: "\\bsk-[A-Za-z0-9_\\-]{20,}",
    sample: `sk-${"A".repeat(20)}`,
    nonMatches: ["task-validation-accounting"],
  },
  {
    source: "ghp_[A-Za-z0-9]{20,}",
    sample: `ghp_${"A".repeat(20)}`,
  },
  {
    source: "github_pat_[A-Za-z0-9_]{20,}",
    sample: `github_pat_${"A".repeat(20)}`,
  },
  {
    source: "AIza[0-9A-Za-z\\-_]{20,}",
    sample: GOOGLE_KEY_COLLISION,
  },
  {
    source:
      "(?s)-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----.*?-----END (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----",
    sample: "-----BEGIN PRIVATE KEY-----\nAAAA\n-----END PRIVATE KEY-----",
  },
  {
    source:
      "(?i)(api[_-]?key|token|secret|password)\\s*[:=]\\s*['\"]?[A-Za-z0-9_\\-]{12,}",
    sample: `token=${"A".repeat(12)}`,
  },
]

const ATTACHMENT_CASES = attachmentCollisionFixtures()

function compilePattern(rawPattern) {
  let source = rawPattern
  const flags = new Set(["g"])
  while (true) {
    const match = source.match(/^\(\?([ims]+)\)/)
    if (!match) break
    for (const flag of match[1]) flags.add(flag)
    source = source.slice(match[0].length)
  }
  return new RegExp(
    source,
    ["g", "i", "m", "s"].filter((flag) => flags.has(flag)).join(""),
  )
}

function assertDefaultDetectorManifest(patterns) {
  assert.deepEqual(
    patterns,
    DEFAULT_DETECTOR_MANIFEST.map((entry) => entry.source),
  )
  for (const entry of DEFAULT_DETECTOR_MANIFEST) {
    assert.match(entry.sample, compilePattern(entry.source))
    for (const candidate of entry.nonMatches ?? []) {
      assert.doesNotMatch(candidate, compilePattern(entry.source))
    }
  }
}

function reasoningMessage(ciphertext, includeItemId = true) {
  const openai = { reasoningEncryptedContent: ciphertext }
  if (includeItemId) openai.itemId = "rs_detector_compatibility"
  return {
    info: {
      id: "msg_detector_reasoning",
      sessionID: "ses_detector_compatibility",
      role: "assistant",
      providerID: "openai",
      modelID: "mock",
    },
    parts: [
      {
        id: "prt_detector_reasoning",
        sessionID: "ses_detector_compatibility",
        messageID: "msg_detector_reasoning",
        type: "reasoning",
        text: "safe",
        metadata: { openai },
      },
    ],
  }
}

function attachmentMessage(fixture) {
  const sessionID = "ses_detector_compatibility"
  const messageID = `msg_detector_${fixture.id}`
  return {
    info: {
      id: messageID,
      sessionID,
      role: "assistant",
      providerID: "openai",
      modelID: "mock",
    },
    parts: [
      {
        id: `prt_detector_tool_${fixture.id}`,
        sessionID,
        messageID,
        type: "tool",
        tool: "read",
        callID: `call_detector_${fixture.id}`,
        state: {
          status: "completed",
          input: { filePath: `/tmp/fixture.${fixture.id}` },
          output: "safe",
          time: { start: 1, end: 2 },
          attachments: [
            {
              id: `prt_detector_file_${fixture.id}`,
              sessionID,
              messageID,
              type: "file",
              mime: fixture.mime,
              url: fixture.url,
            },
          ],
        },
      },
    ],
  }
}

function directUserFileMessage(fixture) {
  const sessionID = "ses_detector_compatibility"
  const messageID = `msg_detector_direct_${fixture.id}`
  return {
    info: {
      id: messageID,
      sessionID,
      role: "user",
    },
    parts: [
      {
        id: `prt_detector_direct_${fixture.id}`,
        sessionID,
        messageID,
        type: "file",
        filename: `fixture.${fixture.id}`,
        mime: fixture.mime,
        url: fixture.url,
      },
    ],
  }
}

function toolPathMessage(path) {
  const sessionID = "ses_detector_compatibility"
  const messageID = "msg_detector_tool_path"
  return {
    info: {
      id: messageID,
      sessionID,
      role: "assistant",
      providerID: "openai",
      modelID: "mock",
    },
    parts: [
      {
        id: "prt_detector_tool_path",
        sessionID,
        messageID,
        type: "tool",
        tool: "read",
        callID: "call_detector_tool_path",
        state: {
          status: "completed",
          input: { path },
          output: "safe",
          time: { start: 1, end: 2 },
        },
      },
    ],
  }
}

function mutableTextMessage(text, index) {
  return {
    info: {
      id: `msg_detector_mutable_${index}`,
      sessionID: "ses_detector_compatibility",
      role: "user",
    },
    parts: [{ type: "text", text }],
  }
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

function defaultAttachmentRedactor(providerLimits = {}) {
  const config = DEFAULT_GATEWAY_CONFIG.secretLeakGuard
  return createSecretRedactor({
    patterns: config.patterns,
    omittableOpaqueAttachmentPatternIndex: 3,
    redactionToken: config.redactionToken,
    limits: {
      maxDepth: config.maxDepth,
      maxNodes: config.maxNodes,
      maxChars: config.maxChars,
    },
    providerLimits: {
      maxMessages: config.providerMaxMessages,
      maxNodes: config.providerMaxNodes,
      maxChars: config.providerMaxChars,
      maxMessageChars: config.providerMaxMessageChars,
      ...providerLimits,
    },
  })
}

test("default detector compatibility manifest is complete and mutation-sensitive", () => {
  const patterns = DEFAULT_GATEWAY_CONFIG.secretLeakGuard.patterns
  assertDefaultDetectorManifest(patterns)
  assert.throws(
    () => assertDefaultDetectorManifest([...patterns, "iVBORw0KGgo[A-Za-z0-9+/=]+"]),
    /Expected values to be strictly deep-equal/,
  )
})

test("default detector does not mistake ordinary task paths for secrets", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-detector-task-path-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: { hooks: { enabled: false, order: [], disabled: [] } },
    })
    const path =
      "/Users/diego/Codes/Projects/ai-loop-wt-durable-task-validation-accounting"
    const message = toolPathMessage(path)
    await plugin["experimental.chat.messages.transform"]({}, { messages: [message] })
    assert.equal(message.parts[0].state.input.path, path)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("explicit broad detector retains configured identifier matching", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-detector-custom-task-path-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: { enabled: false, order: [], disabled: [] },
        secretLeakGuard: { patterns: ["sk-[A-Za-z0-9_\\-]{20,}"] },
      },
    })
    const path =
      "/Users/diego/Codes/Projects/ai-loop-wt-durable-task-validation-accounting"
    await assert.rejects(
      plugin["experimental.chat.messages.transform"](
        {},
        { messages: [toolPathMessage(path)] },
      ),
      (error) =>
        error.code === "immutable_match" &&
        error.patternIndex === 0 &&
        error.locationCode === "immutable_protocol_field",
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("every default detector collision is preserved in qualified reasoning with or without itemId", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-detector-reasoning-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: { hooks: { enabled: false, order: [], disabled: [] } },
    })
    for (const includeItemId of [true, false]) {
      for (const entry of DEFAULT_DETECTOR_MANIFEST) {
        const ciphertext = `opaque-${entry.sample}-ciphertext`
        assert.match(ciphertext, compilePattern(entry.source))
        const message = reasoningMessage(ciphertext, includeItemId)
        await plugin["experimental.chat.messages.transform"]({}, { messages: [message] })
        const openai = message.parts[0].metadata.openai
        assert.equal(openai.reasoningEncryptedContent, ciphertext)
        assert.equal("itemId" in openai, includeItemId)
      }
    }
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("every default detector still redacts ordinary mutable content", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-detector-mutable-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: { hooks: { enabled: false, order: [], disabled: [] } },
    })
    const messages = DEFAULT_DETECTOR_MANIFEST.map((entry, index) =>
      mutableTextMessage(entry.sample, index),
    )
    await plugin["experimental.chat.messages.transform"]({}, { messages })
    for (const [index, entry] of DEFAULT_DETECTOR_MANIFEST.entries()) {
      const text = messages[index].parts[0].text
      assert.equal(text.includes(entry.sample), false)
      assert.equal(text.includes(DEFAULT_GATEWAY_CONFIG.secretLeakGuard.redactionToken), true)
    }
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("pinned tool attachment corpus tolerates Base64 transport collisions", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-detector-attachments-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: { hooks: { enabled: false, order: [], disabled: [] } },
    })
    for (const fixture of ATTACHMENT_CASES) {
      assert.equal(fixture.url.includes(GOOGLE_KEY_COLLISION), true)
      const message = attachmentMessage(fixture)
      await plugin["experimental.chat.messages.transform"]({}, { messages: [message] })
      assert.equal(message.parts[0].state.attachments[0].url, fixture.url)
    }
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("pinned direct user-file corpus tolerates Base64 transport collisions", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-detector-direct-files-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: { hooks: { enabled: false, order: [], disabled: [] } },
    })
    for (const fixture of ATTACHMENT_CASES) {
      const message = directUserFileMessage(fixture)
      await plugin["experimental.chat.messages.transform"]({}, { messages: [message] })
      assert.equal(message.parts[0].url, fixture.url)
    }
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})


test("attachment collision matches are confined to the canonical payload", () => {
  const googlePattern = compilePattern(DEFAULT_DETECTOR_MANIFEST[3].source)
  for (const fixture of ATTACHMENT_CASES) {
    const payloadStart = fixture.url.indexOf(",") + 1
    const matches = [...fixture.url.matchAll(googlePattern)]
    assert.equal(matches.length, 1)
    assert.equal(matches[0].index >= payloadStart, true)
    assert.equal(matches[0].index + matches[0][0].length <= fixture.url.length, true)
  }
})

test("unsupported, mismatched, and parameterized attachment envelopes remain blocked", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-detector-attachment-negative-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: { hooks: { enabled: false, order: [], disabled: [] } },
    })
    const jpeg = ATTACHMENT_CASES.find((fixture) => fixture.mime === "image/jpeg")
    const png = ATTACHMENT_CASES.find((fixture) => fixture.mime === "image/png")
    assert.ok(jpeg)
    assert.ok(png)
    const payloadStart = jpeg.url.indexOf(",") + 1
    const payloadSlash = jpeg.url.indexOf("/", payloadStart)
    assert.equal(payloadSlash >= payloadStart, true)
    const urlSafePayload =
      jpeg.url.slice(0, payloadSlash) + "_" + jpeg.url.slice(payloadSlash + 1)
    assert.equal(urlSafePayload.slice(0, payloadStart), jpeg.url.slice(0, payloadStart))

    const badCrcBytes = Buffer.from(png.bytes)
    badCrcBytes[badCrcBytes.length - 1] ^= 1
    const badCrcUrl = pngDataUrl(badCrcBytes)
    assert.equal(badCrcUrl.includes(GOOGLE_KEY_COLLISION), true)

    const variants = [
      { ...jpeg, mime: "image/png" },
      { ...jpeg, mime: "image/jpg", url: jpeg.url.replace("image/jpeg", "image/jpg") },
      { ...jpeg, mime: "image/gif", url: jpeg.url.replace("image/jpeg", "image/gif") },
      {
        ...jpeg,
        url: jpeg.url.replace("image/jpeg;base64", "image/jpeg;charset=utf-8;base64"),
      },
      { ...jpeg, url: urlSafePayload },
      { ...jpeg, url: `${jpeg.url}AAAA` },
      { ...png, url: badCrcUrl },
    ]
    for (const fixture of variants) {
      await assert.rejects(
        plugin["experimental.chat.messages.transform"](
          {},
          { messages: [attachmentMessage(fixture)] },
        ),
        (error) =>
          error.code === "immutable_match" &&
          error.patternIndex === 3 &&
          error.locationCode === "immutable_protocol_field",
      )
    }
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("direct user-file collisions fail closed outside the exact envelope", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-detector-direct-file-negative-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: { hooks: { enabled: false, order: [], disabled: [] } },
    })
    const png = ATTACHMENT_CASES.find((fixture) => fixture.mime === "image/png")
    assert.ok(png)
    const variants = []
    const addVariant = (mutate) => {
      const message = directUserFileMessage(png)
      mutate(message)
      variants.push(message)
    }
    addVariant((message) => {
      message.info.role = "assistant"
    })
    addVariant((message) => {
      delete message.info.id
    })
    addVariant((message) => {
      delete message.info.sessionID
    })
    addVariant((message) => {
      message.parts[0].type = "text"
    })
    addVariant((message) => {
      delete message.parts[0].id
    })
    addVariant((message) => {
      message.parts[0].messageID = "msg_detector_other"
    })
    addVariant((message) => {
      message.parts[0].sessionID = "ses_detector_other"
    })
    addVariant((message) => {
      message.parts[0].mime = "image/jpg"
      message.parts[0].url = message.parts[0].url.replace("image/png", "image/jpg")
    })
    addVariant((message) => {
      message.parts[0].url = message.parts[0].url.replace(
        "image/png;base64",
        "image/png;charset=utf-8;base64",
      )
    })
    addVariant((message) => {
      message.parts[0].url = `${message.parts[0].url}AAAA`
    })
    addVariant((message) => {
      message.parts[0].url = message.parts[0].url.replace(
        "data:image/png;base64,",
        `data:image/png;${GOOGLE_KEY_COLLISION};base64,`,
      )
    })
    for (const message of variants) {
      await assert.rejects(
        plugin["experimental.chat.messages.transform"]({}, { messages: [message] }),
        (error) =>
          error.code === "immutable_match" &&
          error.patternIndex === 3 &&
          error.locationCode === "immutable_protocol_field",
      )
    }
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("direct user-file collisions remain blocked by explicit detector overrides", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-detector-direct-file-override-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: { enabled: false, order: [], disabled: [] },
        secretLeakGuard: { patterns: ["AIza[0-9A-Za-z\\-_]{20,}"] },
      },
    })
    const png = ATTACHMENT_CASES.find((fixture) => fixture.mime === "image/png")
    assert.ok(png)
    await assert.rejects(
      plugin["experimental.chat.messages.transform"]({}, {
        messages: [directUserFileMessage(png)],
      }),
      (error) => error.code === "immutable_match" && error.patternIndex === 0,
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("multiple attachment collisions are omitted and counted", () => {
  const prefix = Buffer.from("%PDF-1.7\n", "ascii")
  const separator = Buffer.from([0xfb, 0x00, 0x00])
  const payload = collisionBase64Payload(
    prefix,
    Buffer.concat([
      separator,
      Buffer.from(GOOGLE_KEY_COLLISION, "base64"),
      Buffer.from("\n%%EOF\n", "ascii"),
    ]),
  )
  const fixture = {
    id: "pdf-multiple",
    mime: "application/pdf",
    url: `data:application/pdf;base64,${payload}`,
  }
  assert.equal(fixture.url.split(GOOGLE_KEY_COLLISION).length - 1, 2)

  const stats = defaultAttachmentRedactor().redactProviderMessages([
    attachmentMessage(fixture),
  ])
  assert.equal(stats.omittedOpaqueAttachmentMatches, 2)
  assert.equal(stats.matches, 0)

  const directStats = defaultAttachmentRedactor().redactProviderMessages([
    directUserFileMessage(fixture),
  ])
  assert.equal(directStats.omittedOpaqueAttachmentMatches, 2)
  assert.equal(directStats.matches, 0)
})


test("attachment budgets are enforced before Base64 decoding", () => {
  const fixture = ATTACHMENT_CASES.find((entry) => entry.mime === "application/pdf")
  assert.ok(fixture)
  const message = attachmentMessage(fixture)
  const exactMessageChars = jsonStringChars(message)
  const descriptor = Object.getOwnPropertyDescriptor(Buffer, "from")
  assert.ok(descriptor)
  assert.equal(typeof descriptor.value, "function")
  const originalFrom = descriptor.value
  let base64Decodes = 0

  Object.defineProperty(Buffer, "from", {
    ...descriptor,
    value(...args) {
      if (args[1] === "base64") base64Decodes += 1
      return Reflect.apply(originalFrom, this, args)
    },
  })
  try {
    const exactLimits = {
      maxChars: exactMessageChars,
      maxMessageChars: exactMessageChars,
    }
    assert.doesNotThrow(() =>
      defaultAttachmentRedactor(exactLimits).redactProviderMessages([message]),
    )
    assert.equal(base64Decodes, 1)

    base64Decodes = 0
    assert.throws(
      () =>
        defaultAttachmentRedactor({
          maxChars: exactMessageChars,
          maxMessageChars: exactMessageChars - 1,
        }).redactProviderMessages([attachmentMessage(fixture)]),
      (error) => error.code === "text_limit",
    )
    assert.equal(base64Decodes, 0)

    base64Decodes = 0
    assert.throws(
      () =>
        defaultAttachmentRedactor({
          maxMessages: 2,
          maxChars: exactMessageChars,
          maxMessageChars: exactMessageChars,
        }).redactProviderMessages(["x", attachmentMessage(fixture)]),
      (error) => error.code === "text_limit",
    )
    assert.equal(base64Decodes, 0)
  } finally {
    Object.defineProperty(Buffer, "from", descriptor)
  }
})
