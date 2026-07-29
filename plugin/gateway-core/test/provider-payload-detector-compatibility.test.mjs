import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"
import { crc32, deflateSync } from "node:zlib"

import { DEFAULT_GATEWAY_CONFIG } from "../dist/config/schema.js"
import GatewayCorePlugin from "../dist/index.js"
import { createSecretRedactor } from "../dist/hooks/shared/secret-redaction.js"

const GOOGLE_KEY_COLLISION = `AIza${"A".repeat(20)}`

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

function pngChunk(type, data = Buffer.alloc(0)) {
  const typeBytes = Buffer.from(type, "ascii")
  const header = Buffer.alloc(4)
  header.writeUInt32BE(data.length)
  const checksum = Buffer.alloc(4)
  checksum.writeUInt32BE(crc32(Buffer.concat([typeBytes, data])) >>> 0)
  return Buffer.concat([header, typeBytes, data, checksum])
}

function collisionPayload(prefix, suffix) {
  assert.equal(prefix.length % 3, 0)
  const collisionBytes = Buffer.from(GOOGLE_KEY_COLLISION, "base64")
  assert.equal(collisionBytes.toString("base64"), GOOGLE_KEY_COLLISION)
  const payload = Buffer.concat([prefix, collisionBytes, suffix]).toString("base64")
  assert.equal(payload.includes(GOOGLE_KEY_COLLISION), true)
  return payload
}

function attachmentCases() {
  const pngHeader = Buffer.alloc(13)
  pngHeader.writeUInt32BE(1, 0)
  pngHeader.writeUInt32BE(1, 4)
  pngHeader[8] = 8
  pngHeader[9] = 6
  const collisionBytes = Buffer.from(GOOGLE_KEY_COLLISION, "base64")
  const png = Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    pngChunk("IHDR", pngHeader),
    pngChunk("ruSt", Buffer.concat([Buffer.from([0]), collisionBytes])),
    pngChunk("IDAT", deflateSync(Buffer.from([0, 0, 0, 0, 255]))),
    pngChunk("IEND"),
  ])
  const cases = [
    {
      id: "png",
      mime: "image/png",
      url: `data:image/png;base64,${png.toString("base64")}`,
    },
    {
      id: "jpeg",
      mime: "image/jpeg",
      url: `data:image/jpeg;base64,${collisionPayload(
        Buffer.from([0xff, 0xd8, 0xff]),
        Buffer.from([0xff, 0xd9]),
      )}`,
    },
    {
      id: "pdf",
      mime: "application/pdf",
      url: `data:application/pdf;base64,${collisionPayload(
        Buffer.from("%PDF-1.7\n", "ascii"),
        Buffer.from("\n%%EOF\n", "ascii"),
      )}`,
    },
  ]
  for (const fixture of cases) {
    assert.equal(fixture.url.includes(GOOGLE_KEY_COLLISION), true)
  }
  return cases
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

test("every default detector collision is preserved in qualified reasoning ciphertext", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-detector-reasoning-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: { hooks: { enabled: false, order: [], disabled: [] } },
    })
    for (const entry of DEFAULT_DETECTOR_MANIFEST) {
      const ciphertext = `opaque-${entry.sample}-ciphertext`
      assert.match(ciphertext, compilePattern(entry.source))
      const message = reasoningMessage(ciphertext)
      await plugin["experimental.chat.messages.transform"]({}, { messages: [message] })
      assert.equal(
        message.parts[0].metadata.openai.reasoningEncryptedContent,
        ciphertext,
      )
    }
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("qualified reasoning ciphertext remains compatible when itemId is absent", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-detector-reasoning-no-id-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: { hooks: { enabled: false, order: [], disabled: [] } },
    })
    const ciphertext = `opaque-${DEFAULT_DETECTOR_MANIFEST[0].sample}-ciphertext`
    const message = reasoningMessage(ciphertext, false)
    await plugin["experimental.chat.messages.transform"]({}, { messages: [message] })
    assert.equal(message.parts[0].metadata.openai.reasoningEncryptedContent, ciphertext)
    assert.equal("itemId" in message.parts[0].metadata.openai, false)
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
    for (const fixture of attachmentCases()) {
      const message = attachmentMessage(fixture)
      await plugin["experimental.chat.messages.transform"]({}, { messages: [message] })
      assert.equal(message.parts[0].state.attachments[0].url, fixture.url)
    }
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})


test("attachment collision matches are confined to the canonical payload", () => {
  const googlePattern = compilePattern(DEFAULT_DETECTOR_MANIFEST[3].source)
  for (const fixture of attachmentCases()) {
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
    const jpeg = attachmentCases().find((fixture) => fixture.mime === "image/jpeg")
    assert.ok(jpeg)
    const variants = [
      { ...jpeg, mime: "image/png" },
      { ...jpeg, mime: "image/jpg", url: jpeg.url.replace("image/jpeg", "image/jpg") },
      { ...jpeg, mime: "image/gif", url: jpeg.url.replace("image/jpeg", "image/gif") },
      {
        ...jpeg,
        url: jpeg.url.replace("image/jpeg;base64", "image/jpeg;charset=utf-8;base64"),
      },
      { ...jpeg, url: jpeg.url.replace("/", "_") },
      { ...jpeg, url: `${jpeg.url}AAAA` },
    ]
    for (const fixture of variants) {
      await assert.rejects(
        plugin["experimental.chat.messages.transform"](
          {},
          { messages: [attachmentMessage(fixture)] },
        ),
        (error) => error.code === "immutable_match" && error.patternIndex === 3,
      )
    }
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("multiple attachment collisions are omitted, counted, and charged once", () => {
  const collisionBytes = Buffer.from(GOOGLE_KEY_COLLISION, "base64")
  const prefix = Buffer.from("%PDF-1.7\n", "ascii")
  const separator = Buffer.from([0xfb, 0x00, 0x00])
  assert.equal(prefix.length % 3, 0)
  assert.equal(separator.length % 3, 0)
  const bytes = Buffer.concat([
    prefix,
    collisionBytes,
    separator,
    collisionBytes,
    Buffer.from("\n%%EOF\n", "ascii"),
  ])
  const fixture = {
    id: "pdf-multiple",
    mime: "application/pdf",
    url: `data:application/pdf;base64,${bytes.toString("base64")}`,
  }
  assert.equal(fixture.url.split(GOOGLE_KEY_COLLISION).length - 1, 2)
  const config = DEFAULT_GATEWAY_CONFIG.secretLeakGuard
  const redactor = createSecretRedactor({
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
    },
  })
  const message = attachmentMessage(fixture)
  const stats = redactor.redactProviderMessages([message])
  assert.equal(stats.omittedOpaqueAttachmentMatches, 2)
  assert.equal(stats.matches, 0)
  assert.equal(stats.scannedChars >= fixture.url.length, true)
})


test("over-budget collision attachment rejects before envelope decoding", () => {
  const collisionBytes = Buffer.from(GOOGLE_KEY_COLLISION, "base64")
  const pngHeader = Buffer.alloc(13)
  pngHeader.writeUInt32BE(1, 0)
  pngHeader.writeUInt32BE(1, 4)
  pngHeader[8] = 8
  pngHeader[9] = 6
  const png = Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    pngChunk("IHDR", pngHeader),
    pngChunk(
      "ruSt",
      Buffer.concat([Buffer.from([0]), collisionBytes, Buffer.alloc(8 * 1024 * 1024)]),
    ),
    pngChunk("IDAT", deflateSync(Buffer.from([0, 0, 0, 0, 255]))),
    pngChunk("IEND"),
  ])
  const fixture = {
    id: "png-over-budget",
    mime: "image/png",
    url: `data:image/png;base64,${png.toString("base64")}`,
  }
  const config = DEFAULT_GATEWAY_CONFIG.secretLeakGuard
  const redactor = createSecretRedactor({
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
      maxMessageChars: 1_024,
    },
  })
  const start = performance.now()
  assert.throws(
    () => redactor.redactProviderMessages([attachmentMessage(fixture)]),
    (error) => error.code === "text_limit",
  )
  assert.equal(performance.now() - start < 100, true)
})
