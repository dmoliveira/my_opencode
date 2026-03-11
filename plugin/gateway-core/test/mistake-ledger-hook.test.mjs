import assert from "node:assert/strict"
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"
import { createMistakeLedgerHook } from "../dist/hooks/mistake-ledger/index.js"

test("mistake-ledger records done-proof validation deferrals", async () => {
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
    assert.equal(entry.sessionId, "session-mistake-1")
    assert.equal(entry.category, "completion_without_validation")
    assert.equal(entry.sourceHook, "done-proof-enforcer")
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("mistake-ledger records done-proof deferrals in default execution order", async () => {
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
    assert.equal(entry.sessionId, "session-mistake-2")
    assert.equal(entry.category, "completion_without_validation")
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("mistake-ledger records structured output deferrals", async () => {
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
    assert.equal(entry.sessionId, "session-mistake-structured")
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

test("mistake-ledger uses LLM fallback for ambiguous deferral wording", async () => {
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
    assert.equal(entry.sessionId, "session-mistake-llm-1")
    assert.equal(entry.category, "completion_without_validation")
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

test("mistake-ledger shadow mode defers semantic recording", async () => {
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

test("mistake-ledger plugin wiring honors shadow mode without writing ledger entries", async () => {
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
