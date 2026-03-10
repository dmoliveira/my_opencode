import assert from "node:assert/strict"
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

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
