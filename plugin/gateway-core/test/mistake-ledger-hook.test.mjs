import assert from "node:assert/strict"
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

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
