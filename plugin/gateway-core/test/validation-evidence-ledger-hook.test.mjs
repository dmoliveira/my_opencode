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

test("validation-evidence-ledger tracks queued bash commands in order", async () => {
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
          requiredMarkers: ["lint", "test"],
          requireLedgerEvidence: true,
          allowTextFallback: false,
        },
      },
    })

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-ledger-queue" },
      { args: { command: "npm run lint" } },
    )
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-ledger-queue" },
      { args: { command: "npm test" } },
    )

    await plugin["tool.execute.after"](
      { tool: "bash", sessionID: "session-ledger-queue" },
      { output: "lint passed" },
    )
    await plugin["tool.execute.after"](
      { tool: "bash", sessionID: "session-ledger-queue" },
      { output: "tests passed" },
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-ledger-queue" },
      { args: { command: "git status" } },
    )
    const done = { output: "finalizing\n<promise>DONE</promise>" }
    await plugin["tool.execute.after"](
      { tool: "bash", sessionID: "session-ledger-queue" },
      done,
    )

    assert.equal(done.output.includes("PENDING_VALIDATION"), false)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("validation-evidence-ledger treats node --test as test evidence", async () => {
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
          requiredMarkers: ["lint", "test"],
          requireLedgerEvidence: true,
          allowTextFallback: false,
        },
      },
    })

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-ledger-node-test" },
      { args: { command: "npm run lint" } }
    )
    await plugin["tool.execute.after"](
      { tool: "bash", sessionID: "session-ledger-node-test" },
      { output: "lint passed" }
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-ledger-node-test" },
      { args: { command: "node --test plugin/gateway-core/test/todoread-cadence-reminder-hook.test.mjs" } }
    )
    await plugin["tool.execute.after"](
      { tool: "bash", sessionID: "session-ledger-node-test" },
      { output: "tests passed" }
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-ledger-node-test" },
      { args: { command: "git status" } }
    )
    const done = { output: "finalizing\n<promise>DONE</promise>" }
    await plugin["tool.execute.after"](
      { tool: "bash", sessionID: "session-ledger-node-test" },
      done,
    )

    assert.equal(done.output.includes("PENDING_VALIDATION"), false)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("validation-evidence-ledger treats repo selftest commands as test evidence", async () => {
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
          requiredMarkers: ["test"],
          requireLedgerEvidence: true,
          allowTextFallback: false,
        },
      },
    })

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-ledger-selftest" },
      { args: { command: "python3 scripts/selftest.py" } },
    )
    await plugin["tool.execute.after"](
      { tool: "bash", sessionID: "session-ledger-selftest" },
      { output: "selftest passed" },
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-ledger-selftest" },
      { args: { command: "git status" } },
    )
    const done = { output: "finalizing\n<promise>DONE</promise>" }
    await plugin["tool.execute.after"](
      { tool: "bash", sessionID: "session-ledger-selftest" },
      done,
    )

    assert.equal(done.output.includes("PENDING_VALIDATION"), false)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("validation-evidence-ledger treats make install-test as test evidence", async () => {
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
          requiredMarkers: ["test"],
          requireLedgerEvidence: true,
          allowTextFallback: false,
        },
      },
    })

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-ledger-install-test" },
      { args: { command: "make install-test" } },
    )
    await plugin["tool.execute.after"](
      { tool: "bash", sessionID: "session-ledger-install-test" },
      { output: "install test passed" },
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-ledger-install-test" },
      { args: { command: "git status" } },
    )
    const done = { output: "finalizing\n<promise>DONE</promise>" }
    await plugin["tool.execute.after"](
      { tool: "bash", sessionID: "session-ledger-install-test" },
      done,
    )

    assert.equal(done.output.includes("PENDING_VALIDATION"), false)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
