import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

function createPlugin(directory) {
  return GatewayCorePlugin({
    directory,
    config: {
      hooks: {
        enabled: true,
        order: ["task-resume-info"],
        disabled: [],
      },
      taskResumeInfo: { enabled: true },
    },
  })
}

test("task-resume-info appends task_id resume hint", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-task-resume-info-"))
  try {
    const plugin = createPlugin(directory)
    const output = { output: "Task completed. task_id: abc-123" }
    await plugin["tool.execute.after"]({ tool: "task", sessionID: "session-task-1" }, output)
    assert.match(String(output.output), /Resume hint:/)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("task-resume-info appends continuation hint for continue loop marker", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-task-resume-info-"))
  try {
    const plugin = createPlugin(directory)
    const output = { output: "Still pending\n<CONTINUE-LOOP>" }
    await plugin["tool.execute.after"]({ tool: "task", sessionID: "session-task-2" }, output)
    assert.match(String(output.output), /Continuation hint:/)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("task-resume-info does not duplicate hints already present", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-task-resume-info-"))
  try {
    const plugin = createPlugin(directory)
    const output = {
      output:
        "task_id: abc\nResume hint: keep the returned task_id and reuse it to continue the same subagent session.\n<CONTINUE-LOOP>\nContinuation hint: pending work remains; continue execution directly and avoid asking for extra confirmation turns.",
    }
    await plugin["tool.execute.after"]({ tool: "task", sessionID: "session-task-3" }, output)

    const text = String(output.output)
    const resumeCount = (text.match(/Resume hint:/g) ?? []).length
    const continuationCount = (text.match(/Continuation hint:/g) ?? []).length
    assert.equal(resumeCount, 1)
    assert.equal(continuationCount, 1)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
