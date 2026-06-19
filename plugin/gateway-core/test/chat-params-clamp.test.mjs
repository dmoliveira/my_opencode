import assert from "node:assert/strict"
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

test("chat.params clamps kvforge output budget below local context limit", async () => {
  const plugin = GatewayCorePlugin({
    directory: process.cwd(),
    config: {
      hooks: {
        enabled: false,
        order: [],
        disabled: [],
      },
    },
  })

  const output = {
    temperature: 0,
    topP: 1,
    topK: 0,
    maxOutputTokens: 32000,
    options: {},
  }

  await plugin["chat.params"](
    {
      sessionID: "session-kvforge-clamp",
      agent: "build",
      model: { providerID: "kvforge", modelID: "gpt-5.4-fast" },
      provider: { id: "kvforge" },
      message: { role: "user", content: "Reply with OK" },
    },
    output,
  )

  assert.equal(output.maxOutputTokens, 31744)
})

test("chat.params leaves smaller budgets unchanged", async () => {
  const plugin = GatewayCorePlugin({
    directory: process.cwd(),
    config: {
      hooks: {
        enabled: false,
        order: [],
        disabled: [],
      },
    },
  })

  const output = {
    temperature: 0,
    topP: 1,
    topK: 0,
    maxOutputTokens: 2048,
    options: {},
  }

  await plugin["chat.params"](
    {
      sessionID: "session-kvforge-unchanged",
      agent: "build",
      model: { providerID: "kvforge", modelID: "gpt-5.4-fast" },
      provider: { id: "kvforge" },
      message: { role: "user", content: "Reply with OK" },
    },
    output,
  )

  assert.equal(output.maxOutputTokens, 2048)
})

test("chat.params records routing drift when runtime model differs", { concurrency: false }, async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-routing-drift-"))
  mkdirSync(join(directory, "agent", "specs"), { recursive: true })
  writeFileSync(
    join(directory, "agent", "orchestrator.md"),
    "---\nmodel: openai/gpt-5.3-codex\n---\n",
  )
  writeFileSync(
    join(directory, "agent", "specs", "orchestrator.json"),
    JSON.stringify({ mode: "primary", metadata: { default_category: "balanced" }, tools: {} }),
  )
  const previous = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
  process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = "1"

  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: false,
          order: [],
          disabled: [],
        },
      },
    })

    const output = {
      temperature: 0,
      topP: 1,
      topK: 0,
      maxOutputTokens: 2048,
      options: {},
    }

    await plugin["chat.params"](
      {
        sessionID: "session-routing-drift",
        agent: "orchestrator",
        model: { providerID: "openai", modelID: "gpt-5.4" },
        provider: { id: "openai" },
        message: { role: "user", content: "Reply with OK" },
      },
      output,
    )

    const auditPath = join(directory, ".opencode", "gateway-events.jsonl")
    const events = readFileSync(auditPath, "utf-8")
      .split(/\r?\n/)
      .filter(Boolean)
      .map((line) => JSON.parse(line))
    const observed = events.find(
      (entry) => entry.reason_code === "agent_runtime_model_observed",
    )
    const drift = events.find(
      (entry) => entry.reason_code === "agent_model_routing_drift_detected",
    )

    assert.equal(observed?.agent, "orchestrator")
    assert.equal(observed?.actual_model, "openai/gpt-5.4")
    assert.equal(drift?.agent, "orchestrator")
    assert.equal(drift?.expected_category, "balanced")
    assert.equal(drift?.expected_model, "openai/gpt-5.3-codex")
    assert.equal(drift?.actual_model, "openai/gpt-5.4")
  } finally {
    if (previous === undefined) {
      delete process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
    } else {
      process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = previous
    }
    rmSync(directory, { recursive: true, force: true })
  }
})


test("tool.definition compacts verbose built-in tool descriptions", async () => {
  const plugin = GatewayCorePlugin({
    directory: process.cwd(),
    config: {
      hooks: {
        enabled: false,
        order: [],
        disabled: [],
      },
    },
  })

  const output = {
    description:
      "Read a file or directory from the local filesystem. If the path does not exist, an error is returned.\n\nUsage notes and examples omitted.",
    parameters: {
      type: "object",
      properties: {
        filePath: { type: "string" },
      },
    },
  }

  await plugin["tool.definition"]({ toolID: "read" }, output)

  assert.equal(output.description, "Read a local file or directory by absolute path.")
  assert.deepEqual(output.parameters, {
    type: "object",
    properties: {
      filePath: { type: "string" },
    },
  })
})

test("tool.definition leaves unknown tools unchanged", async () => {
  const plugin = GatewayCorePlugin({
    directory: process.cwd(),
    config: {
      hooks: {
        enabled: false,
        order: [],
        disabled: [],
      },
    },
  })

  const output = {
    description: "Custom tool description.",
    parameters: { type: "object", properties: {} },
  }

  await plugin["tool.definition"]({ toolID: "custom_tool" }, output)

  assert.equal(output.description, "Custom tool description.")
})
