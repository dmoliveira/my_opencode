import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

test("agent-reservation-guard enforces reservation marker when configured", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-reservation-"))
  const previous = process.env.MY_TEST_RES
  delete process.env.MY_TEST_RES
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["agent-reservation-guard"],
          disabled: [],
        },
        agentReservationGuard: {
          enabled: true,
          enforce: true,
          reservationEnvKeys: ["MY_TEST_RES"],
        },
      },
    })

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "write", sessionID: "session-reservation" },
        { args: { filePath: "src/a.ts" } },
      ),
      /Missing active file reservation marker/,
    )

    process.env.MY_TEST_RES = "true"
    await plugin["tool.execute.before"](
      { tool: "write", sessionID: "session-reservation" },
      { args: { filePath: "src/a.ts" } },
    )
  } finally {
    if (previous === undefined) {
      delete process.env.MY_TEST_RES
    } else {
      process.env.MY_TEST_RES = previous
    }
    rmSync(directory, { recursive: true, force: true })
  }
})
