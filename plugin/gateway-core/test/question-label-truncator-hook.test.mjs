import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

test("question-label-truncator shortens long option labels", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-question-label-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: { enabled: true, order: ["question-label-truncator"], disabled: [] },
        questionLabelTruncator: { enabled: true, maxLength: 12 },
      },
    })
    const output = {
      args: {
        questions: [
          {
            options: [{ label: "A very long answer option label" }],
          },
        ],
      },
    }
    await plugin["tool.execute.before"]({ tool: "question", sessionID: "session-q" }, output)
    assert.equal(output.args.questions[0].options[0].label, "A very lo...")
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
