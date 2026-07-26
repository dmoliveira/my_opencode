import assert from "node:assert/strict"
import { mkdtempSync, readFileSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

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
          { type: "reasoning", text: "secret=ReasoningSecret_123456" },
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
