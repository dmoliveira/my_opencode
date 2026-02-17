import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"
import { createToolOutputTruncatorHook } from "../dist/hooks/tool-output-truncator/index.js"

test("tool-output-truncator hook truncates configured tool output", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-truncator-hook-"))
  try {
    const hook = createToolOutputTruncatorHook({
      directory,
      enabled: true,
      maxChars: 500,
      maxLines: 20,
      tools: ["bash"],
    })
    const output = {
      output: Array.from({ length: 25 }, (_, idx) => `line-${idx + 1}`).join("\n"),
    }

    await hook.event("tool.execute.after", {
      input: {
        tool: "bash",
        sessionID: "session-1",
      },
      output,
      directory,
    })

    assert.equal(output.output.split("\n").length, 20)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("tool-output-truncator ignores unsupported tool names", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-truncator-hook-"))
  try {
    const hook = createToolOutputTruncatorHook({
      directory,
      enabled: true,
      maxChars: 20,
      maxLines: 2,
      tools: ["bash"],
    })
    const output = {
      output: "line-1\nline-2\nline-3",
    }

    await hook.event("tool.execute.after", {
      input: {
        tool: "read",
        sessionID: "session-1",
      },
      output,
      directory,
    })

    assert.equal(output.output, "line-1\nline-2\nline-3")
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("gateway plugin dispatches tool.execute.after to truncator hook", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-truncator-plugin-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["tool-output-truncator"],
          disabled: ["global-process-pressure"],
        },
        autopilotLoop: {
          enabled: false,
          maxIterations: 0,
          completionMode: "promise",
          completionPromise: "DONE",
          orphanMaxAgeHours: 12,
        },
        toolOutputTruncator: {
          enabled: true,
          maxChars: 500,
          maxLines: 20,
          tools: ["bash"],
        },
      },
    })

    const output = {
      output: Array.from({ length: 25 }, (_, idx) => `line-${idx + 1}`).join("\n"),
    }
    await plugin["tool.execute.after"]({ tool: "bash", sessionID: "s-1" }, output)
    assert.equal(output.output.split("\n").length, 20)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
