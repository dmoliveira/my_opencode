import assert from "node:assert/strict"
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

test("chat.params skips drift audit for subagents with explicit model pins", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-routing-subagent-"))
  mkdirSync(join(directory, "agent", "specs"), { recursive: true })
  writeFileSync(
    join(directory, "agent", "reviewer.md"),
    "---\nmodel: openai/gpt-5.4\n---\n",
  )
  writeFileSync(
    join(directory, "agent", "specs", "reviewer.json"),
    JSON.stringify({ mode: "subagent", metadata: { default_category: "critical" }, tools: {} }),
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
        sessionID: "session-subagent-no-drift",
        agent: "reviewer",
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
    const drift = events.find(
      (entry) => entry.reason_code === "agent_model_routing_drift_detected",
    )

    assert.equal(drift, undefined)
  } finally {
    if (previous === undefined) {
      delete process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
    } else {
      process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = previous
    }
    rmSync(directory, { recursive: true, force: true })
  }
})
