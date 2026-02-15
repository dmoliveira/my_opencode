import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

test("validation-evidence-ledger allows DONE when required checks were executed", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-validation-ledger-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["validation-evidence-ledger", "done-proof-enforcer"],
          disabled: [],
        },
        validationEvidenceLedger: {
          enabled: true,
        },
        doneProofEnforcer: {
          enabled: true,
          requiredMarkers: ["lint", "test", "build"],
          requireLedgerEvidence: true,
          allowTextFallback: false,
        },
      },
    })

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-ledger-1" },
      { args: { command: "npm run lint" } },
    )
    await plugin["tool.execute.after"](
      { tool: "bash", sessionID: "session-ledger-1" },
      { output: "Lint passed" },
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-ledger-1" },
      { args: { command: "npm test" } },
    )
    await plugin["tool.execute.after"](
      { tool: "bash", sessionID: "session-ledger-1" },
      { output: "All tests passed" },
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-ledger-1" },
      { args: { command: "npm run build" } },
    )
    await plugin["tool.execute.after"](
      { tool: "bash", sessionID: "session-ledger-1" },
      { output: "Build passed" },
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-ledger-1" },
      { args: { command: "git status" } },
    )
    const output = { output: "Ready to finish\n<promise>DONE</promise>" }
    await plugin["tool.execute.after"]({ tool: "bash", sessionID: "session-ledger-1" }, output)

    assert.ok(output.output.includes("<promise>DONE</promise>"))
    assert.equal(output.output.includes("PENDING_VALIDATION"), false)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
