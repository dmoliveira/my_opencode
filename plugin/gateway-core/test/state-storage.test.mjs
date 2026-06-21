import test from "node:test"
import assert from "node:assert/strict"
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"

import {
  cleanupOrphanGatewayLoop,
  loadGatewayState,
  nowIso,
  resolveGatewayStatePath,
  saveGatewayState,
} from "../dist/state/storage.js"

function withTempDir(run) {
  const directory = mkdtempSync(join(tmpdir(), "gateway-core-test-"))
  try {
    run(directory)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
}

test("cleanupOrphanGatewayLoop deactivates stale active loop", () => {
  withTempDir((directory) => {
    saveGatewayState(directory, {
      activeLoop: {
        active: true,
        sessionId: "s-1",
        objective: "continue",
        completionMode: "promise",
        completionPromise: "DONE",
        iteration: 1,
        maxIterations: 100,
        startedAt: "2025-01-01T00:00:00Z",
      },
      lastUpdatedAt: nowIso(),
    })

    const result = cleanupOrphanGatewayLoop(directory, 1)
    assert.equal(result.changed, true)
    assert.equal(result.reason, "stale_loop_deactivated")
    assert.equal(loadGatewayState(directory)?.activeLoop?.active, false)
  })
})

test("cleanupOrphanGatewayLoop keeps fresh loop active", () => {
  withTempDir((directory) => {
    saveGatewayState(directory, {
      activeLoop: {
        active: true,
        sessionId: "s-2",
        objective: "continue",
        completionMode: "promise",
        completionPromise: "DONE",
        iteration: 1,
        maxIterations: 100,
        startedAt: nowIso(),
      },
      lastUpdatedAt: nowIso(),
    })

    const result = cleanupOrphanGatewayLoop(directory, 12)
    assert.equal(result.changed, false)
    assert.equal(result.reason, "within_age_limit")
    assert.equal(loadGatewayState(directory)?.activeLoop?.active, true)
  })
})

test("saveGatewayState round-trips concise mode state", () => {
  withTempDir((directory) => {
    saveGatewayState(directory, {
      activeLoop: null,
      conciseMode: {
        mode: "full",
        source: "test",
        sessionId: "ses-test-1",
        activatedAt: nowIso(),
        updatedAt: nowIso(),
      },
      lastUpdatedAt: nowIso(),
    })

    const state = loadGatewayState(directory)
    assert.equal(state?.conciseMode?.mode, "full")
    assert.equal(state?.conciseMode?.source, "test")
    assert.equal(state?.conciseMode?.sessionId, "ses-test-1")
  })
})

test("saveGatewayState preserves existing concise mode when caller omits it", () => {
  withTempDir((directory) => {
    saveGatewayState(directory, {
      activeLoop: null,
      conciseMode: {
        mode: "lite",
        source: "test",
        sessionId: "ses-test-2",
        activatedAt: nowIso(),
        updatedAt: nowIso(),
      },
      lastUpdatedAt: nowIso(),
    })

    saveGatewayState(directory, {
      activeLoop: {
        active: true,
        sessionId: "s-3",
        objective: "continue",
        completionMode: "promise",
        completionPromise: "DONE",
        iteration: 1,
        maxIterations: 5,
        startedAt: nowIso(),
      },
      lastUpdatedAt: nowIso(),
    })

    const state = loadGatewayState(directory)
    assert.equal(state?.conciseMode?.mode, "lite")
    assert.equal(state?.activeLoop?.sessionId, "s-3")
  })
})

test("saveGatewayState writes provided concise mode without fallback state dependency", () => {
  withTempDir((directory) => {
    const path = resolveGatewayStatePath(directory)
    mkdirSync(join(directory, ".opencode"), { recursive: true })
    writeFileSync(path, "{not-json}\n", "utf-8")

    saveGatewayState(directory, {
      activeLoop: null,
      conciseMode: {
        mode: "review",
        source: "test",
        sessionId: "ses-test-3",
        activatedAt: nowIso(),
        updatedAt: nowIso(),
      },
      lastUpdatedAt: nowIso(),
      source: "write",
    })

    const state = loadGatewayState(directory)
    assert.equal(state?.conciseMode?.mode, "review")
    assert.equal(state?.conciseMode?.sessionId, "ses-test-3")
    assert.equal(state?.source, "write")
  })
})

test("loadGatewayState drops legacy concise mode entries without session id", () => {
  withTempDir((directory) => {
    saveGatewayState(directory, {
      activeLoop: null,
      conciseMode: {
        mode: "full",
        source: "legacy",
        sessionId: "",
        activatedAt: nowIso(),
        updatedAt: nowIso(),
      },
      lastUpdatedAt: nowIso(),
    })
    const state = loadGatewayState(directory)
    assert.equal(state?.conciseMode, null)
  })
})

test("loadGatewayState reloads external concise mode changes after cache warmup", () => {
  withTempDir((directory) => {
    saveGatewayState(directory, {
      activeLoop: null,
      conciseMode: {
        mode: "lite",
        source: "initial",
        sessionId: "ses-initial",
        activatedAt: nowIso(),
        updatedAt: nowIso(),
      },
      lastUpdatedAt: nowIso(),
    })
    const first = loadGatewayState(directory)
    assert.equal(first?.conciseMode?.mode, "lite")
    assert.equal(first?.conciseMode?.sessionId, "ses-initial")

    writeFileSync(
      resolveGatewayStatePath(directory),
      `${JSON.stringify({
        activeLoop: null,
        conciseMode: {
          mode: "full",
          source: "external",
          sessionId: "ses-external",
          activatedAt: nowIso(),
          updatedAt: nowIso(),
        },
        lastUpdatedAt: nowIso(),
      }, null, 2)}\n`,
      "utf-8",
    )

    const second = loadGatewayState(directory)
    assert.equal(second?.conciseMode?.mode, "full")
    assert.equal(second?.conciseMode?.sessionId, "ses-external")
    assert.equal(second?.conciseMode?.source, "external")
  })
})
