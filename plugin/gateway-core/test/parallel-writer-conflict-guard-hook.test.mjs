import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

test("parallel-writer-conflict-guard blocks when active writer count exceeds limit", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-parallel-writer-"))
  process.env.MY_OPENCODE_ACTIVE_WRITERS = "3"
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["parallel-writer-conflict-guard"],
          disabled: [],
        },
        parallelWriterConflictGuard: {
          enabled: true,
          maxConcurrentWriters: 2,
          writerCountEnvKeys: ["MY_OPENCODE_ACTIVE_WRITERS"],
          reservationPathsEnvKeys: ["MY_OPENCODE_FILE_RESERVATION_PATHS"],
          activeReservationPathsEnvKeys: ["MY_OPENCODE_ACTIVE_RESERVATION_PATHS"],
          enforceReservationCoverage: true,
        },
      },
    })

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "edit", sessionID: "session-parallel-writer" },
        { args: { filePath: "src/a.ts" } },
      ),
      /exceeds limit/,
    )
  } finally {
    delete process.env.MY_OPENCODE_ACTIVE_WRITERS
    rmSync(directory, { recursive: true, force: true })
  }
})

test("parallel-writer-conflict-guard blocks uncovered edit path when reservation coverage is enforced", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-parallel-writer-"))
  process.env.MY_OPENCODE_ACTIVE_WRITERS = "1"
  process.env.MY_OPENCODE_FILE_RESERVATION_PATHS = "docs/**"
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["parallel-writer-conflict-guard"],
          disabled: [],
        },
        parallelWriterConflictGuard: {
          enabled: true,
          maxConcurrentWriters: 2,
          writerCountEnvKeys: ["MY_OPENCODE_ACTIVE_WRITERS"],
          reservationPathsEnvKeys: ["MY_OPENCODE_FILE_RESERVATION_PATHS"],
          activeReservationPathsEnvKeys: ["MY_OPENCODE_ACTIVE_RESERVATION_PATHS"],
          enforceReservationCoverage: true,
        },
      },
    })

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "write", sessionID: "session-parallel-writer" },
        { args: { filePath: "src/a.ts" } },
      ),
      /outside reserved ownership/,
    )
  } finally {
    delete process.env.MY_OPENCODE_ACTIVE_WRITERS
    delete process.env.MY_OPENCODE_FILE_RESERVATION_PATHS
    rmSync(directory, { recursive: true, force: true })
  }
})

test("parallel-writer-conflict-guard blocks overlap with active reservation", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-parallel-writer-"))
  process.env.MY_OPENCODE_ACTIVE_WRITERS = "1"
  process.env.MY_OPENCODE_FILE_RESERVATION_PATHS = "src/owned/**"
  process.env.MY_OPENCODE_ACTIVE_RESERVATION_PATHS = "src/shared/**"
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["parallel-writer-conflict-guard"],
          disabled: [],
        },
        parallelWriterConflictGuard: {
          enabled: true,
          maxConcurrentWriters: 2,
          writerCountEnvKeys: ["MY_OPENCODE_ACTIVE_WRITERS"],
          reservationPathsEnvKeys: ["MY_OPENCODE_FILE_RESERVATION_PATHS"],
          activeReservationPathsEnvKeys: ["MY_OPENCODE_ACTIVE_RESERVATION_PATHS"],
          enforceReservationCoverage: false,
        },
      },
    })

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "edit", sessionID: "session-parallel-writer" },
        { args: { filePath: "src/shared/a.ts" } },
      ),
      /overlaps an active reservation/,
    )
  } finally {
    delete process.env.MY_OPENCODE_ACTIVE_WRITERS
    delete process.env.MY_OPENCODE_FILE_RESERVATION_PATHS
    delete process.env.MY_OPENCODE_ACTIVE_RESERVATION_PATHS
    rmSync(directory, { recursive: true, force: true })
  }
})
