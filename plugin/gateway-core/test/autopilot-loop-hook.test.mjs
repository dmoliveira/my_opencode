import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import { createAutopilotLoopHook } from "../dist/hooks/autopilot-loop/index.js"
import { loadGatewayState } from "../dist/state/storage.js"

test("autopilot-loop hook accepts command from input args shape", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-loop-hook-"))
  try {
    const hook = createAutopilotLoopHook({
      directory,
      defaults: {
        enabled: true,
        maxIterations: 7,
        completionMode: "promise",
        completionPromise: "DONE",
      },
    })

    await hook.event("tool.execute.before", {
      input: {
        tool: "slashcommand",
        sessionId: "session-123",
        args: { command: "/autopilot go --goal \"ship\"" },
      },
      output: {},
      directory,
    })

    const state = loadGatewayState(directory)
    assert.ok(state?.activeLoop)
    assert.equal(state?.activeLoop?.active, true)
    assert.equal(state?.activeLoop?.sessionId, "session-123")
    assert.equal(state?.activeLoop?.objective, "ship")
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("autopilot-loop hook starts loop from command.execute.before", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-loop-hook-"))
  try {
    const hook = createAutopilotLoopHook({
      directory,
      defaults: {
        enabled: true,
        maxIterations: 0,
        completionMode: "promise",
        completionPromise: "DONE",
      },
    })

    await hook.event("command.execute.before", {
      input: {
        command: "autopilot-go",
        arguments: '--goal "session objective"',
        sessionID: "session-variant",
      },
      output: {},
      directory,
    })

    const state = loadGatewayState(directory)
    assert.ok(state?.activeLoop)
    assert.equal(state?.activeLoop?.active, true)
    assert.equal(state?.activeLoop?.sessionId, "session-variant")
    assert.equal(state?.activeLoop?.objective, "session objective")
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("autopilot-loop hook parses rendered command template invocations", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-loop-hook-"))
  try {
    const hook = createAutopilotLoopHook({
      directory,
      defaults: {
        enabled: true,
        maxIterations: 0,
        completionMode: "promise",
        completionPromise: "DONE",
      },
    })

    await hook.event("tool.execute.before", {
      input: {
        tool: "command",
        sessionID: "session-template",
      },
      output: {
        args: {
          command:
            'python3 "$HOME/.config/opencode/my_opencode/scripts/autopilot_command.py" go --goal "ship" --json',
        },
      },
      directory,
    })

    const state = loadGatewayState(directory)
    assert.ok(state?.activeLoop)
    assert.equal(state?.activeLoop?.active, true)
    assert.equal(state?.activeLoop?.sessionId, "session-template")
    assert.equal(state?.activeLoop?.objective, "ship")
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("autopilot-loop hook ignores non-start autopilot subcommands", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-loop-hook-"))
  try {
    const hook = createAutopilotLoopHook({
      directory,
      defaults: {
        enabled: true,
        maxIterations: 0,
        completionMode: "promise",
        completionPromise: "DONE",
      },
    })

    await hook.event("tool.execute.before", {
      input: {
        tool: "slashcommand",
        sessionID: "session-status",
        args: { command: "/autopilot status --json" },
      },
      output: {},
      directory,
    })

    const state = loadGatewayState(directory)
    assert.equal(state, null)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("autopilot-loop pause preserves objective and resume restores it", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-loop-hook-"))
  try {
    const hook = createAutopilotLoopHook({
      directory,
      defaults: {
        enabled: true,
        maxIterations: 25,
        completionMode: "promise",
        completionPromise: "DONE",
      },
    })

    await hook.event("tool.execute.before", {
      input: {
        tool: "slashcommand",
        sessionID: "session-pause-resume",
        args: { command: '/autopilot go --goal "ship objective" --done-criteria "item 1; item 2"' },
      },
      output: {},
      directory,
    })

    await hook.event("tool.execute.before", {
      input: {
        tool: "slashcommand",
        sessionID: "session-pause-resume",
        args: { command: "/autopilot pause" },
      },
      output: {},
      directory,
    })

    let state = loadGatewayState(directory)
    assert.equal(state?.activeLoop?.active, false)
    assert.equal(state?.activeLoop?.objective, "ship objective")
    assert.deepEqual(state?.activeLoop?.doneCriteria, ["item 1", "item 2"])

    await hook.event("tool.execute.before", {
      input: {
        tool: "slashcommand",
        sessionID: "session-pause-resume",
        args: { command: "/autopilot resume" },
      },
      output: {},
      directory,
    })

    state = loadGatewayState(directory)
    assert.equal(state?.activeLoop?.active, true)
    assert.equal(state?.activeLoop?.objective, "ship objective")
    assert.deepEqual(state?.activeLoop?.doneCriteria, ["item 1", "item 2"])
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("autopilot-loop registers objective summary with stable context id", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-loop-hook-"))
  try {
    const calls = []
    const hook = createAutopilotLoopHook({
      directory,
      defaults: {
        enabled: true,
        maxIterations: 7,
        completionMode: "promise",
        completionPromise: "DONE",
      },
      collector: {
        register(sessionId, options) {
          calls.push({ sessionId, options })
        },
      },
    })

    await hook.event("tool.execute.before", {
      input: {
        tool: "slashcommand",
        sessionID: "session-summary",
        args: { command: '/autopilot go --goal "ship summary"' },
      },
      output: {},
      directory,
    })

    assert.equal(calls.length, 1)
    assert.equal(calls[0]?.sessionId, "session-summary")
    assert.equal(calls[0]?.options?.source, "autopilot-loop")
    assert.equal(calls[0]?.options?.id, "objective-summary")
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
