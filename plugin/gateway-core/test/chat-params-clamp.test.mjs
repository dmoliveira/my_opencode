import assert from "node:assert/strict"
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
