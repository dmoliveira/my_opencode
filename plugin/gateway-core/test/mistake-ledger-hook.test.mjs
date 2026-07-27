import assert from "node:assert/strict"
import {
  chmodSync,
  constants,
  existsSync,
  linkSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  statSync,
  symlinkSync,
  writeFileSync,
} from "node:fs"
import { spawnSync } from "node:child_process"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

const LEDGER_STORAGE_SUPPORTED =
  typeof process.getuid === "function" &&
  typeof constants.O_NOFOLLOW === "number" &&
  constants.O_NOFOLLOW !== 0

function ledgerTest(name, fn) {
  return test(name, { skip: !LEDGER_STORAGE_SUPPORTED }, fn)
}

import GatewayCorePlugin from "../dist/index.js"
import { createMistakeLedgerHook } from "../dist/hooks/mistake-ledger/index.js"

ledgerTest("mistake-ledger records done-proof validation deferrals", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-mistake-ledger-"))
  try {
    const hook = createMistakeLedgerHook({
      directory,
      enabled: true,
      path: ".opencode/mistake-ledger.jsonl",
    })

    await hook.event("tool.execute.after", {
      input: { tool: "bash", sessionID: "session-mistake-1" },
      output: {
        output:
          "done\n<promise>PENDING_VALIDATION</promise>\n\n[done-proof-enforcer] Completion token deferred until validation evidence is included (validation).",
      },
      directory,
    })

    const ledgerPath = join(directory, ".opencode", "mistake-ledger.jsonl")
    assert.equal(existsSync(ledgerPath), true)
    const lines = readFileSync(ledgerPath, "utf-8").trim().split("\n")
    assert.equal(lines.length, 1)
    const entry = JSON.parse(lines[0])
    assert.deepEqual(Object.keys(entry).sort(), ["category", "sourceHook", "ts"])
    assert.equal(entry.category, "completion_without_validation")
    assert.equal(entry.sourceHook, "done-proof-enforcer")
    assert.equal(JSON.stringify(entry).includes("session-mistake-1"), false)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

ledgerTest("mistake-ledger records done-proof deferrals in default execution order", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-mistake-ledger-"))
  try {
    const hook = createMistakeLedgerHook({
      directory,
      enabled: true,
      path: ".opencode/mistake-ledger.jsonl",
    })

    await hook.event("tool.execute.after", {
      input: { tool: "bash", sessionID: "session-mistake-2" },
      output: {
        output:
          "done\n<promise>PENDING_VALIDATION</promise>\n\n[done-proof-enforcer] Completion token deferred until validation evidence is included (validation).",
      },
      directory,
    })

    const ledgerPath = join(directory, ".opencode", "mistake-ledger.jsonl")
    assert.equal(existsSync(ledgerPath), true)
    const lines = readFileSync(ledgerPath, "utf-8").trim().split("\n")
    assert.equal(lines.length, 1)
    const entry = JSON.parse(lines[0])
    assert.equal(entry.category, "completion_without_validation")
    assert.equal(Object.hasOwn(entry, "sessionId"), false)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

ledgerTest("mistake-ledger records structured output deferrals", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-mistake-ledger-"))
  try {
    const hook = createMistakeLedgerHook({
      directory,
      enabled: true,
      path: ".opencode/mistake-ledger.jsonl",
    })
    await hook.event("tool.execute.after", {
      input: { tool: "bash", sessionID: "session-mistake-structured" },
      output: {
        output: {
          stdout:
            "done\n<promise>PENDING_VALIDATION</promise>\n\n[done-proof-enforcer] Completion token deferred until validation evidence is included (validation).",
          stderr: "warning text",
        },
      },
      directory,
    })
    const ledgerPath = join(directory, ".opencode", "mistake-ledger.jsonl")
    assert.equal(existsSync(ledgerPath), true)
    const entry = JSON.parse(readFileSync(ledgerPath, "utf-8").trim())
    assert.equal(entry.category, "completion_without_validation")
    assert.equal(Object.hasOwn(entry, "sessionId"), false)
    assert.equal(Object.hasOwn(entry, "summary"), false)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

function mockDecisionRuntime(char, mode = "assist") {
  return {
    config: { mode },
    async decide(request) {
      return {
        mode,
        accepted: true,
        char,
        raw: char,
        durationMs: 1,
        model: "test-model",
        templateId: request.templateId,
        meaning: char === "Y" ? "record_completion_without_validation" : "ignore",
      }
    },
  }
}

function createPlugin(directory, decisionRuntime) {
  return GatewayCorePlugin({
    directory,
    config: {
      hooks: {
        enabled: true,
        order: ["mistake-ledger"],
        disabled: [],
      },
      mistakeLedger: {
        enabled: true,
        path: ".opencode/mistake-ledger.jsonl",
      },
      llmDecisionRuntime: decisionRuntime
        ? {
            enabled: true,
            mode: decisionRuntime.config.mode,
            hookModes: { "mistake-ledger": decisionRuntime.config.mode },
            command: "opencode",
            model: "openai/gpt-5.1-codex-mini",
            timeoutMs: 1000,
            maxPromptChars: 200,
            maxContextChars: 200,
            enableCache: true,
            cacheTtlMs: 10000,
            maxCacheEntries: 8,
          }
        : undefined,
    },
    createLlmDecisionRuntime: decisionRuntime ? (() => decisionRuntime) : undefined,
  })
}

ledgerTest("mistake-ledger uses LLM fallback for ambiguous deferral wording", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-mistake-ledger-"))
  const previousAudit = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
  process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = "1"
  try {
    const hook = createMistakeLedgerHook({
      directory,
      enabled: true,
      path: ".opencode/mistake-ledger.jsonl",
      decisionRuntime: mockDecisionRuntime("Y"),
    })
    await hook.event("tool.execute.after", {
      input: { tool: "bash", sessionID: "session-mistake-llm-1" },
      output: {
        output:
          "done\n<promise>PENDING_VALIDATION</promise>\n\nCompletion is held until the missing validation proof is included.",
      },
      directory,
    })

    const ledgerPath = join(directory, ".opencode", "mistake-ledger.jsonl")
    assert.equal(existsSync(ledgerPath), true)
    const entry = JSON.parse(readFileSync(ledgerPath, "utf-8").trim())
    assert.equal(entry.category, "completion_without_validation")
    assert.equal(Object.hasOwn(entry, "sessionId"), false)
    assert.equal(Object.hasOwn(entry, "summary"), false)
    const events = readFileSync(join(directory, ".opencode", "gateway-events.jsonl"), "utf-8")
      .trim()
      .split("\n")
      .map((line) => JSON.parse(line))
    const recorded = events.find((event) => event.reason_code === "llm_mistake_ledger_decision_recorded")
    assert.ok(recorded)
    assert.equal(recorded.session_id, "session-mistake-llm-1")
    assert.equal(recorded.llm_decision_char, "Y")
  } finally {
    if (previousAudit === undefined) {
      delete process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
    } else {
      process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = previousAudit
    }
    rmSync(directory, { recursive: true, force: true })
  }
})

ledgerTest("mistake-ledger shadow mode defers semantic recording", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-mistake-ledger-"))
  const previousAudit = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
  process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = "1"
  try {
    const hook = createMistakeLedgerHook({
      directory,
      enabled: true,
      path: ".opencode/mistake-ledger.jsonl",
      decisionRuntime: mockDecisionRuntime("Y", "shadow"),
    })
    await hook.event("tool.execute.after", {
      input: { tool: "bash", sessionID: "session-mistake-llm-2" },
      output: {
        output:
          "done\n<promise>PENDING_VALIDATION</promise>\n\nCompletion is held until the missing validation proof is included.",
      },
      directory,
    })

    const ledgerPath = join(directory, ".opencode", "mistake-ledger.jsonl")
    assert.equal(existsSync(ledgerPath), false)
    const events = readFileSync(join(directory, ".opencode", "gateway-events.jsonl"), "utf-8")
      .trim()
      .split("\n")
      .map((line) => JSON.parse(line))
    const deferred = events.find((event) => event.reason_code === "llm_mistake_ledger_shadow_deferred")
    assert.ok(deferred)
    assert.equal(deferred.session_id, "session-mistake-llm-2")
    assert.equal(deferred.llm_decision_char, "Y")
  } finally {
    if (previousAudit === undefined) {
      delete process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
    } else {
      process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = previousAudit
    }
    rmSync(directory, { recursive: true, force: true })
  }
})

ledgerTest("mistake-ledger plugin wiring honors shadow mode without writing ledger entries", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-mistake-ledger-"))
  const previousAudit = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
  process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = "1"
  try {
    let decideCalls = 0
    const plugin = createPlugin(directory, {
      config: { mode: "shadow" },
      async decide(request) {
        decideCalls += 1
        return {
          mode: "shadow",
          accepted: true,
          char: "Y",
          raw: "Y",
          durationMs: 1,
          model: "test-model",
          templateId: request.templateId,
          meaning: "record_completion_without_validation",
        }
      },
    })
    await plugin["tool.execute.after"](
      { tool: "bash", sessionID: "session-mistake-plugin-shadow" },
      {
        output:
          "done\n<promise>PENDING_VALIDATION</promise>\n\nCompletion is held until the missing validation proof is included.",
      },
    )

    const ledgerPath = join(directory, ".opencode", "mistake-ledger.jsonl")
    assert.equal(existsSync(ledgerPath), false)
    assert.equal(decideCalls, 1)
  } finally {
    if (previousAudit === undefined) {
      delete process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
    } else {
      process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = previousAudit
    }
    rmSync(directory, { recursive: true, force: true })
  }
})

ledgerTest("mistake-ledger rejects custom paths without touching workspace files", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-mistake-ledger-"))
  const victimPath = join(directory, "victim.txt")
  try {
    writeFileSync(victimPath, "victim-sentinel", "utf-8")
    assert.throws(
      () =>
        createMistakeLedgerHook({
          directory,
          enabled: true,
          path: "victim.txt",
        }),
      /mistake ledger path must be \.opencode\/mistake-ledger\.jsonl/,
    )
    assert.equal(readFileSync(victimPath, "utf-8"), "victim-sentinel")
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

ledgerTest("mistake-ledger ignores payload directory as storage authority", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-mistake-ledger-"))
  const escapedDirectory = mkdtempSync(join(tmpdir(), "gateway-mistake-ledger-escape-"))
  try {
    const hook = createMistakeLedgerHook({
      directory,
      enabled: true,
      path: ".opencode/mistake-ledger.jsonl",
    })
    await hook.event("tool.execute.after", {
      input: { tool: "bash", sessionID: "payload-directory-canary" },
      output: {
        output: "[done-proof-enforcer] Completion token deferred",
      },
      directory: escapedDirectory,
    })
    assert.equal(existsSync(join(directory, ".opencode", "mistake-ledger.jsonl")), true)
    assert.equal(existsSync(join(escapedDirectory, ".opencode", "mistake-ledger.jsonl")), false)
  } finally {
    rmSync(directory, { recursive: true, force: true })
    rmSync(escapedDirectory, { recursive: true, force: true })
  }
})

ledgerTest("mistake-ledger repairs safe existing file mode to owner-only", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-mistake-ledger-"))
  try {
    const ledgerDirectory = join(directory, ".opencode")
    const ledgerPath = join(ledgerDirectory, "mistake-ledger.jsonl")
    mkdirSync(ledgerDirectory, { mode: 0o755 })
    writeFileSync(ledgerPath, "", { mode: 0o644 })
    chmodSync(ledgerPath, 0o644)
    const hook = createMistakeLedgerHook({
      directory,
      enabled: true,
      path: ".opencode/mistake-ledger.jsonl",
    })
    await hook.event("tool.execute.after", {
      input: { tool: "bash", sessionID: "mode-canary" },
      output: { output: "[done-proof-enforcer] Completion token deferred" },
      directory,
    })
    assert.equal(statSync(ledgerPath).mode & 0o777, 0o600)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

ledgerTest("mistake-ledger refuses final symlinks and preserves the victim", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-mistake-ledger-"))
  try {
    const ledgerDirectory = join(directory, ".opencode")
    const ledgerPath = join(ledgerDirectory, "mistake-ledger.jsonl")
    const victimPath = join(directory, "victim.txt")
    mkdirSync(ledgerDirectory)
    writeFileSync(victimPath, "victim-sentinel", "utf-8")
    symlinkSync(victimPath, ledgerPath)
    const hook = createMistakeLedgerHook({
      directory,
      enabled: true,
      path: ".opencode/mistake-ledger.jsonl",
    })
    await assert.rejects(
      hook.event("tool.execute.after", {
        input: { tool: "bash", sessionID: "symlink-canary" },
        output: { output: "[done-proof-enforcer] Completion token deferred" },
      }),
      /unsafe mistake ledger file/,
    )
    assert.equal(readFileSync(victimPath, "utf-8"), "victim-sentinel")
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

ledgerTest("mistake-ledger refuses parent symlinks", () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-mistake-ledger-"))
  const targetDirectory = mkdtempSync(join(tmpdir(), "gateway-mistake-ledger-parent-"))
  try {
    symlinkSync(targetDirectory, join(directory, ".opencode"))
    assert.throws(
      () =>
        createMistakeLedgerHook({
          directory,
          enabled: true,
          path: ".opencode/mistake-ledger.jsonl",
        }),
      /unsafe mistake ledger directory/,
    )
    assert.equal(existsSync(join(targetDirectory, "mistake-ledger.jsonl")), false)
  } finally {
    rmSync(directory, { recursive: true, force: true })
    rmSync(targetDirectory, { recursive: true, force: true })
  }
})

ledgerTest("mistake-ledger refuses hardlinks and preserves the victim", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-mistake-ledger-"))
  try {
    const ledgerDirectory = join(directory, ".opencode")
    const ledgerPath = join(ledgerDirectory, "mistake-ledger.jsonl")
    const victimPath = join(directory, "victim.txt")
    mkdirSync(ledgerDirectory)
    writeFileSync(victimPath, "victim-sentinel", "utf-8")
    linkSync(victimPath, ledgerPath)
    const hook = createMistakeLedgerHook({
      directory,
      enabled: true,
      path: ".opencode/mistake-ledger.jsonl",
    })
    await assert.rejects(
      hook.event("tool.execute.after", {
        input: { tool: "bash", sessionID: "hardlink-canary" },
        output: { output: "[done-proof-enforcer] Completion token deferred" },
      }),
      /regular single-link file/,
    )
    assert.equal(readFileSync(victimPath, "utf-8"), "victim-sentinel")
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

ledgerTest("mistake-ledger refuses FIFO targets", async (context) => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-mistake-ledger-"))
  try {
    const ledgerDirectory = join(directory, ".opencode")
    const ledgerPath = join(ledgerDirectory, "mistake-ledger.jsonl")
    mkdirSync(ledgerDirectory)
    const created = spawnSync("mkfifo", [ledgerPath], { encoding: "utf-8" })
    if (created.status !== 0) {
      context.skip("mkfifo unavailable")
      return
    }
    const hook = createMistakeLedgerHook({
      directory,
      enabled: true,
      path: ".opencode/mistake-ledger.jsonl",
    })
    await assert.rejects(
      hook.event("tool.execute.after", {
        input: { tool: "bash", sessionID: "fifo-canary" },
        output: { output: "[done-proof-enforcer] Completion token deferred" },
      }),
      /regular single-link file/,
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

ledgerTest("mistake-ledger refuses group-writable parent directories", () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-mistake-ledger-"))
  try {
    const ledgerDirectory = join(directory, ".opencode")
    mkdirSync(ledgerDirectory, { mode: 0o700 })
    chmodSync(ledgerDirectory, 0o770)
    assert.throws(
      () =>
        createMistakeLedgerHook({
          directory,
          enabled: true,
          path: ".opencode/mistake-ledger.jsonl",
        }),
      /directory is group\/world writable/,
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
