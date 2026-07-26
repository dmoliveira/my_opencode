import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

test("semantic-output-summarizer compresses repetitive large output", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-semantic-summarizer-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["semantic-output-summarizer"],
          disabled: [],
        },
        semanticOutputSummarizer: {
          enabled: true,
          minChars: 200,
          minLines: 10,
          maxSummaryLines: 3,
        },
      },
    })

    const noisy = Array.from({ length: 20 }, () => "ERROR timeout while fetching dependency").join("\n")
    const output = { output: noisy }
    await plugin["tool.execute.after"]({ tool: "bash", sessionID: "session-summarizer" }, output)

    assert.ok(output.output.includes("semantic-output-summarizer"))
    assert.ok(output.output.includes("Key diagnostics"))
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("semantic-output-summarizer compresses structured stdout payloads in place", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-semantic-summarizer-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: { enabled: true, order: ["semantic-output-summarizer"], disabled: [] },
        semanticOutputSummarizer: {
          enabled: true,
          minChars: 200,
          minLines: 10,
          maxSummaryLines: 3,
        },
      },
    })
    const noisy = Array.from({ length: 20 }, () => "ERROR timeout while fetching dependency").join("\n")
    const output = { output: { stdout: noisy, stderr: "warning text" } }
    await plugin["tool.execute.after"]({ tool: "bash", sessionID: "session-summarizer-structured" }, output)
    assert.match(String(output.output.stdout), /semantic-output-summarizer/)
    assert.equal(String(output.output.stderr), "warning text")
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("enabled summarizer runs before truncation for legacy and custom orders", async () => {
  const orders = [
    ["tool-output-truncator", "semantic-output-summarizer"],
    ["tool-output-truncator"],
  ]
  for (const order of orders) {
    const directory = mkdtempSync(join(tmpdir(), "gateway-semantic-order-"))
    try {
      const plugin = GatewayCorePlugin({
        directory,
        config: {
          hooks: { enabled: true, order, disabled: [] },
          semanticOutputSummarizer: {
            enabled: true,
            minChars: 500,
            minLines: 30,
            maxSummaryLines: 3,
          },
          toolOutputTruncator: {
            enabled: true,
            maxChars: 400,
            maxLines: 20,
            tools: ["bash"],
          },
        },
      })
      const noisy = Array.from(
        { length: 40 },
        () => "ERROR timeout while fetching dependency",
      ).join("\n")
      const output = { output: noisy }
      await plugin["tool.execute.after"](
        { tool: "bash", sessionID: "session-summarizer-order" },
        output,
      )
      assert.match(String(output.output), /semantic-output-summarizer/)
    } finally {
      rmSync(directory, { recursive: true, force: true })
    }
  }
})
