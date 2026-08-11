import assert from "node:assert/strict"
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import { createCodememoryMilestoneBridgeHook } from "../dist/hooks/codememory-milestone-bridge/index.js"
import GatewayCorePlugin from "../dist/index.js"

function waitForQueue() {
  return new Promise((resolve) => setTimeout(resolve, 20))
}

function createSpawner({
  autoClose = true,
  closeCode = 0,
  throwError = false,
  ignoreTermination = false,
} = {}) {
  const calls = []
  const children = []
  const spawnProcess = (command, args, options) => {
    if (throwError) {
      throw new Error("spawn unavailable")
    }
    const listeners = new Map()
    const child = {
      pid: undefined,
      once(event, listener) {
        listeners.set(event, listener)
        if (event === "close" && autoClose) {
          setImmediate(() => listener(closeCode, null))
        }
        return child
      },
      kill(signal = "SIGTERM") {
        child.killed = true
        child.signals.push(signal)
        if (ignoreTermination && signal !== "SIGKILL") {
          return true
        }
        listeners.get("close")?.(null, signal)
        return true
      },
      killed: false,
      signals: [],
      release(code = closeCode) {
        listeners.get("close")?.(code, null)
      },
    }
    calls.push({ command, args, options, child })
    children.push(child)
    return child
  }
  return { calls, children, spawnProcess }
}

function bridge(directory, spawner, overrides = {}) {
  return createCodememoryMilestoneBridgeHook({
    directory,
    enabled: true,
    command: "oc",
    timeoutMs: 25,
    maxQueueEntries: 4,
    spawnProcess: spawner.spawnProcess,
    ...overrides,
  })
}

function withDirectory(run) {
  const directory = mkdtempSync(join(tmpdir(), "gateway-codememory-"))
  return Promise.resolve(run(directory)).finally(() => {
    rmSync(directory, { recursive: true, force: true })
  })
}

test("milestone bridge is disabled without spawning oc", async () => {
  await withDirectory(async (directory) => {
    const spawner = createSpawner()
    const hook = bridge(directory, spawner, { enabled: false })
    await hook.event("tool.execute.after", {
      input: { tool: "task", sessionID: "session-disabled", callID: "call-disabled" },
      output: { args: { subagent_type: "reviewer" }, output: "completed" },
      directory,
    })
    await waitForQueue()
    assert.equal(spawner.calls.length, 0)
  })
})

test("bridge emits delegation milestone with fixed oc argv", async () => {
  await withDirectory(async (directory) => {
    const spawner = createSpawner()
    const hook = bridge(directory, spawner)
    await hook.event("tool.execute.after", {
      input: { tool: "task", sessionID: "session-task", callID: "call-task" },
      output: {
        args: { subagent_type: "reviewer", category: "critical" },
        output: "review completed",
      },
      directory,
    })
    await waitForQueue()
    assert.equal(spawner.calls.length, 1)
    const call = spawner.calls[0]
    assert.equal(call.command, "oc")
    assert.deepEqual(call.args.slice(0, 2), ["event", "noted"])
    assert.equal(call.args.includes("--target"), false)
    assert.equal(call.args[call.args.indexOf("--actor") + 1], "gateway-core:codememory-milestone-bridge")
    assert.equal(call.options.cwd, directory)
    assert.equal(call.options.shell, undefined)
    assert.match(call.args[2], /milestone=delegation outcome=passed/)
    assert.match(call.args[2], /subagent=reviewer category=critical/)
  })
})

test("bridge records before-hook failures and ignores zero-failure prose", async () => {
  await withDirectory(async (directory) => {
    const spawner = createSpawner()
    const hook = bridge(directory, spawner)
    const taskPayload = {
      input: {
        tool: "task",
        sessionID: "session-failure",
        callID: "call-failure",
        args: { command: "task" },
      },
      output: { args: { subagent_type: "reviewer" } },
      directory,
    }

    await hook.event("tool.execute.before", taskPayload)
    await hook.event("tool.execute.before.error", {
      ...taskPayload,
      error: new Error("blocked by policy"),
    })
    await hook.event("tool.execute.after", {
      ...taskPayload,
      input: { ...taskPayload.input, callID: "call-success" },
      output: {
        args: { subagent_type: "reviewer" },
        output: "10 passed, 0 failed",
      },
    })
    await waitForQueue()

    assert.equal(spawner.calls.length, 2)
    assert.match(spawner.calls[0].args[2], /milestone=delegation outcome=failed/)
    assert.match(spawner.calls[1].args[2], /milestone=delegation outcome=passed/)
  })
})

test("gateway dispatch reports a before failure when the bridge follows the failing guard", async () => {
  await withDirectory(async (directory) => {
    const previousAudit = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
    writeFileSync(join(directory, "event"), "process.exit(0)\n")
    process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = "1"
    try {
      const plugin = GatewayCorePlugin({
        directory,
        config: {
          hooks: {
            enabled: true,
            order: ["dangerous-command-guard", "codememory-milestone-bridge"],
            disabled: [],
          },
          dangerousCommandGuard: {
            enabled: true,
            blockedPatterns: ["make validate"],
          },
          codememoryMilestoneBridge: {
            enabled: true,
            command: process.execPath,
            timeoutMs: 500,
            maxQueueEntries: 4,
          },
        },
      })

      await assert.rejects(
        plugin["tool.execute.before"](
          { tool: "bash", sessionID: "session-before-failure" },
          { args: { command: "make validate" } },
        ),
        /Blocked dangerous bash command/,
      )
      await new Promise((resolve) => setTimeout(resolve, 100))

      const audit = readFileSync(join(directory, ".opencode", "gateway-events.jsonl"), "utf8")
      assert.match(audit, /"hook":"codememory-milestone-bridge"/)
      assert.match(audit, /"reason_code":"codememory_event_sent"/)
    } finally {
      if (previousAudit === undefined) {
        delete process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
      } else {
        process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = previousAudit
      }
    }
  })
})

test("bridge classifies validation and GitHub milestones without raw command text", async () => {
  await withDirectory(async (directory) => {
    const spawner = createSpawner()
    const hook = bridge(directory, spawner)
    const payload = (command, exit, callID) => ({
      input: { tool: "bash", sessionID: "session-bash", callID, args: { command } },
      output: { metadata: { exit }, output: "ok" },
      directory,
    })

    await hook.event("tool.execute.after", payload("make validate", 0, "call-validation"))
    await hook.event("tool.execute.after", payload("gh pr create --title secret-title --body secret-body", 0, "call-create"))
    await hook.event("tool.execute.after", payload("gh pr merge 42 --merge --delete-branch", 1, "call-merge"))
    await waitForQueue()

    assert.equal(spawner.calls.length, 3)
    assert.match(spawner.calls[0].args[2], /milestone=validation outcome=passed/)
    assert.match(spawner.calls[0].args[2], /categories=lint/)
    assert.doesNotMatch(spawner.calls[1].args[2], /secret-title|secret-body/)
    assert.match(spawner.calls[1].args[2], /milestone=pr_create outcome=passed/)
    assert.match(spawner.calls[2].args[2], /milestone=pr_merge outcome=failed/)
  })
})

test("bridge deduplicates the active request and bounds pending work", async () => {
  await withDirectory(async (directory) => {
    const spawner = createSpawner({ autoClose: false })
    const hook = bridge(directory, spawner, { maxQueueEntries: 1 })
    const event = (callID, sessionID = "session-queue") => ({
      input: { tool: "task", sessionID, callID },
      output: { args: { subagent_type: "verifier" }, output: "completed" },
      directory,
    })

    await hook.event("tool.execute.after", event("call-one"))
    await hook.event("tool.execute.after", event("call-one"))
    await hook.event("tool.execute.after", event("call-two"))
    await hook.event("tool.execute.after", event("call-three"))
    assert.equal(spawner.calls.length, 1)
    spawner.children[0].release()
    await waitForQueue()
    assert.equal(spawner.calls.length, 2)
  })
})

test("bridge fails open on nonzero, spawn, and timeout outcomes", async () => {
  await withDirectory(async (directory) => {
    const failedSpawner = createSpawner({ closeCode: 2 })
    const failedHook = bridge(directory, failedSpawner)
    await failedHook.event("tool.execute.after", {
      input: { tool: "task", sessionID: "session-failed", callID: "call-failed" },
      output: { args: { subagent_type: "verifier" }, output: "completed" },
      directory,
    })
    await waitForQueue()
    assert.equal(failedSpawner.calls.length, 1)

    const spawnError = createSpawner({ throwError: true })
    const spawnErrorHook = bridge(directory, spawnError)
    await spawnErrorHook.event("tool.execute.after", {
      input: { tool: "task", sessionID: "session-spawn-error", callID: "call-spawn-error" },
      output: { args: { subagent_type: "verifier" }, output: "completed" },
      directory,
    })
    await waitForQueue()

    const timeoutSpawner = createSpawner({ autoClose: false })
    const timeoutHook = bridge(directory, timeoutSpawner, { timeoutMs: 5 })
    await timeoutHook.event("tool.execute.after", {
      input: { tool: "task", sessionID: "session-timeout", callID: "call-timeout" },
      output: { args: { subagent_type: "verifier" }, output: "completed" },
      directory,
    })
    await waitForQueue()
    assert.equal(timeoutSpawner.children[0].killed, true)
  })
})

test("timeout escalates a child that ignores termination", async () => {
  await withDirectory(async (directory) => {
    const spawner = createSpawner({ autoClose: false, ignoreTermination: true })
    const hook = bridge(directory, spawner, { timeoutMs: 5 })
    await hook.event("tool.execute.after", {
      input: { tool: "task", sessionID: "session-kill", callID: "call-kill" },
      output: { args: { subagent_type: "verifier" }, output: "completed" },
      directory,
    })
    await new Promise((resolve) => setTimeout(resolve, 300))

    assert.deepEqual(spawner.children[0].signals, ["SIGTERM", "SIGKILL"])
  })
})

test("session deletion keeps pending milestones and does not cancel the active child", async () => {
  await withDirectory(async (directory) => {
    const spawner = createSpawner({ autoClose: false })
    const hook = bridge(directory, spawner, { maxQueueEntries: 2 })
    const event = (callID) => ({
      input: { tool: "task", sessionID: "session-delete", callID },
      output: { args: { subagent_type: "reviewer" }, output: "completed" },
      directory,
    })

    await hook.event("tool.execute.after", event("call-active"))
    await hook.event("tool.execute.after", event("call-pending"))
    await hook.event("session.deleted", { properties: { info: { id: "session-delete" } }, directory })
    spawner.children[0].release()
    await waitForQueue()
    assert.equal(spawner.calls.length, 2)
  })
})
