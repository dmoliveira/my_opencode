import assert from "node:assert/strict"
import { chmodSync, mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import {
  EXECUTION_STATUS_FILE,
  MAX_STATE_BYTES,
  readExecutionStatus,
  statusForSession,
} from "../dist/state-reader.js"

async function withTempDir(run) {
  const directory = mkdtempSync(join(tmpdir(), "gateway-sidebar-reader-"))
  try {
    return await run(directory)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
}

function writeState(directory, status) {
  const stateDirectory = join(directory, ".opencode")
  mkdirSync(stateDirectory, { recursive: true, mode: 0o700 })
  chmodSync(stateDirectory, 0o700)
  const path = join(stateDirectory, EXECUTION_STATUS_FILE)
  writeFileSync(path, JSON.stringify({ executionStatus: status }))
  chmodSync(path, 0o600)
  return path
}

test("reader accepts a private, fresh per-session status entry", async () => {
  await withTempDir(async (directory) => {
    writeState(directory, {
      version: 1,
      sessions: {
        "ses-reader": {
          sessionId: "ses-reader",
          last: "Validation passed",
          next: "Review changes",
          updatedAt: new Date().toISOString(),
        },
      },
    })
    const snapshot = await readExecutionStatus(directory)
    assert.equal(statusForSession(snapshot, "ses-reader")?.last, "Validation passed")
  })
})

test("reader accepts a bounded shared gateway state larger than the status projection", async () => {
  await withTempDir(async (directory) => {
    const path = writeState(directory, {
      version: 1,
      sessions: {
        "ses-large": {
          sessionId: "ses-large",
          last: "Validation passed",
          next: "Review changes",
          updatedAt: new Date().toISOString(),
        },
      },
    })
    const state = JSON.parse(readFileSync(path, "utf8"))
    state.padding = "x".repeat(16 * 1024)
    writeFileSync(path, JSON.stringify(state))
    chmodSync(path, 0o600)

    const snapshot = await readExecutionStatus(directory)
    assert.equal(statusForSession(snapshot, "ses-large")?.next, "Review changes")
  })
})

test("reader fails closed for unsafe state files", async () => {
  await withTempDir(async (directory) => {
    const target = writeState(directory, {
      version: 1,
      sessions: {},
    })
    chmodSync(target, 0o644)
    assert.equal(await readExecutionStatus(directory), null)

    chmodSync(target, 0o600)
    writeFileSync(target, "x".repeat(MAX_STATE_BYTES + 1))
    assert.equal(await readExecutionStatus(directory), null)

    const replacement = join(directory, "replacement.json")
    writeFileSync(replacement, "{}")
    rmSync(target)
    symlinkSync(replacement, target)
    assert.equal(await readExecutionStatus(directory), null)

    rmSync(target)
    writeFileSync(target, JSON.stringify({ executionStatus: { version: 1, sessions: {} } }))
    chmodSync(target, 0o600)
    chmodSync(join(directory, ".opencode"), 0o755)
    assert.equal(await readExecutionStatus(directory), null)
  })
})

test("reader accepts labels up to the gateway configuration maximum", async () => {
  await withTempDir(async (directory) => {
    const label = "x".repeat(160)
    writeState(directory, {
      version: 1,
      sessions: {
        "ses-max-label": {
          sessionId: "ses-max-label",
          last: label,
          next: label,
          updatedAt: new Date().toISOString(),
        },
      },
    })
    assert.equal(statusForSession(await readExecutionStatus(directory), "ses-max-label")?.last, label)
  })
})

test("reader drops ANSI-bearing status entries", async () => {
  await withTempDir(async (directory) => {
    writeState(directory, {
      version: 1,
      sessions: {
        "ses-unsafe": {
          sessionId: "ses-unsafe",
          last: "\u001b[31munsafe",
          next: "Continue",
          updatedAt: new Date().toISOString(),
        },
      },
    })
    const snapshot = await readExecutionStatus(directory)
    assert.equal(statusForSession(snapshot, "ses-unsafe"), null)
  })
})
