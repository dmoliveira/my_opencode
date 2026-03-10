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
    const plugin = GatewayCorePlugin({
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
      },
    })

    await plugin["tool.execute.after"](
      { tool: "bash", sessionID: "session-mistake-1" },
      { output: "done\n<promise>PENDING_VALIDATION</promise>\n\n[done-proof-enforcer] Completion token deferred until validation evidence is included (validation)." },
    )

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
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["validation-evidence-ledger", "done-proof-enforcer", "mistake-ledger"],
          disabled: [],
        },
        validationEvidenceLedger: { enabled: true },
        doneProofEnforcer: {
          enabled: true,
          requiredMarkers: ["validation"],
          requireLedgerEvidence: true,
          allowTextFallback: false,
        },
        mistakeLedger: {
          enabled: true,
          path: ".opencode/mistake-ledger.jsonl",
        },
      },
    })

    const output = { output: "done\n<promise>DONE</promise>" }
    await plugin["tool.execute.after"]({ tool: "bash", sessionID: "session-mistake-2" }, output)

    const ledgerPath = join(directory, ".opencode", "mistake-ledger.jsonl")
    assert.equal(existsSync(ledgerPath), true)
    const lines = readFileSync(ledgerPath, "utf-8").trim().split("\n")
    assert.equal(lines.length, 1)
    assert.match(output.output, /PENDING_VALIDATION/)
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
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: { enabled: true, order: ["mistake-ledger"], disabled: [] },
        mistakeLedger: { enabled: true, path: ".opencode/mistake-ledger.jsonl" },
      },
    })
    await plugin["tool.execute.after"](
      { tool: "bash", sessionID: "session-mistake-structured" },
      { output: { stdout: "done\n<promise>PENDING_VALIDATION</promise>\n\n[done-proof-enforcer] Completion token deferred until validation evidence is included (validation).", stderr: "warning text" } },
    )
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

test("mistake-ledger uses LLM fallback for ambiguous deferral wording", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-mistake-ledger-"))
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
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("mistake-ledger shadow mode defers semantic recording", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-mistake-ledger-"))
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
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
