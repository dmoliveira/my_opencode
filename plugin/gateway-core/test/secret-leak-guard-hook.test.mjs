import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

test("secret-leak-guard redacts known secret patterns", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-secret-guard-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: { enabled: true, order: ["secret-leak-guard"], disabled: [] },
        secretLeakGuard: {
          enabled: true,
          redactionToken: "[REDACTED]",
          patterns: ["sk-[A-Za-z0-9]{10,}"],
        },
      },
    })

    const output = { output: "token sk-1234567890ABCDE should not appear" }
    await plugin["tool.execute.after"]({ tool: "bash", sessionID: "session-secret" }, output)
    assert.equal(output.output.includes("sk-1234567890ABCDE"), false)
    assert.equal(output.output.includes("[REDACTED]"), true)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
