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
