import test from "node:test"
import assert from "node:assert/strict"
import { spawn } from "node:child_process"
import {
  chmodSync,
  linkSync,
  lstatSync,
  mkdtempSync,
  mkdirSync,
  readFileSync,
  readlinkSync,
  readdirSync,
  renameSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { fileURLToPath } from "node:url"

import {
  cleanupOrphanGatewayLoop,
  GatewayStateProtocolError,
  LOCK_DIRECTORY_NAME,
  LOCK_RECOVERY_GUIDANCE,
  OWNER_TOKEN_NAME,
  PRIVATE_DIRECTORY_MODE,
  PRIVATE_FILE_MODE,
  STAGE_PREFIX,
  gatewayStateLockStatus,
  loadGatewayState,
  loadRawGatewayState,
  nowIso,
  resolveGatewayStatePath,
  saveGatewayConciseMode,
  saveGatewayState,
  transactGatewayStateDomain,
  updateGatewayStateDomain,
} from "../dist/state/storage.js"

function withTempDir(run) {
  const directory = mkdtempSync(join(tmpdir(), "gateway-core-test-"))
  try {
    run(directory)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
}

function seedRawState(directory) {
  const stateDirectory = join(directory, ".opencode")
  mkdirSync(stateDirectory, { recursive: true, mode: PRIVATE_DIRECTORY_MODE })
  chmodSync(stateDirectory, PRIVATE_DIRECTORY_MODE)
  const path = resolveGatewayStatePath(directory)
  writeFileSync(
    path,
    `${JSON.stringify(
      {
        activeLoop: {
          active: true,
          sessionId: "seed",
          objective: "seed",
          completionMode: "promise",
          completionPromise: "DONE",
          iteration: 0,
          maxIterations: 100,
          startedAt: "2026-07-27T00:00:00Z",
          unknownLoop: { sentinel: "loop" },
        },
        conciseMode: {
          mode: "lite",
          source: "seed",
          sessionId: "seed",
          activatedAt: "2026-07-27T00:00:00Z",
          updatedAt: "2026-07-27T00:00:00Z",
          unknownConcise: { sentinel: "concise" },
        },
        lastUpdatedAt: "2026-07-27T00:00:00Z",
        source: "seed",
        unknownRoot: { sentinel: "root" },
      },
      null,
      2,
    )}\n`,
    { encoding: "utf-8", mode: PRIVATE_FILE_MODE },
  )
  chmodSync(path, PRIVATE_FILE_MODE)
  return path
}

function lockNodeSnapshot(path) {
  const stats = lstatSync(path, { bigint: true })
  return {
    dev: stats.dev,
    ino: stats.ino,
    mode: stats.mode,
    nlink: stats.nlink,
    size: stats.size,
    kind: stats.isFile() ? "file" : stats.isSymbolicLink() ? "symlink" : stats.isDirectory() ? "directory" : "other",
    content: stats.isFile()
      ? readFileSync(path)
      : stats.isSymbolicLink()
        ? readlinkSync(path)
        : null,
  }
}

function replaceLockGeneration(lock, tokenMode) {
  const displaced = `${lock}.displaced`
  renameSync(lock, displaced)
  mkdirSync(lock, { mode: PRIVATE_DIRECTORY_MODE })
  chmodSync(lock, PRIVATE_DIRECTORY_MODE)
  const token = join(lock, OWNER_TOKEN_NAME)
  writeFileSync(token, `${"b".repeat(64)}\n`, { mode: tokenMode })
  chmodSync(token, tokenMode)
  return {
    displaced,
    lock: lockNodeSnapshot(lock),
    owner: lockNodeSnapshot(token),
  }
}

function runWriter(directory, domain, count = 30) {
  const fixture = fileURLToPath(new URL("./fixtures/gateway-state-writer.mjs", import.meta.url))
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [fixture, directory, domain, String(count)], {
      stdio: ["ignore", "pipe", "pipe"],
    })
    let stdout = ""
    let stderr = ""
    child.stdout.setEncoding("utf-8")
    child.stderr.setEncoding("utf-8")
    child.stdout.on("data", (chunk) => {
      stdout += chunk
    })
    child.stderr.on("data", (chunk) => {
      stderr += chunk
    })
    const timer = setTimeout(() => child.kill("SIGKILL"), 15_000)
    child.once("error", reject)
    child.once("close", (code, signal) => {
      clearTimeout(timer)
      if (code !== 0) {
        reject(new Error(`writer ${domain} failed code=${code} signal=${signal}: ${stderr}`))
        return
      }
      resolve(JSON.parse(stdout))
    })
  })
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
      lastUpdatedAt: nowIso(),
    })
    saveGatewayConciseMode(
      directory,
      {
        mode: "full",
        source: "test",
        sessionId: "ses-test-1",
        activatedAt: nowIso(),
        updatedAt: nowIso(),
      },
      { lastUpdatedAt: nowIso() },
    )

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
      lastUpdatedAt: nowIso(),
    })
    saveGatewayConciseMode(
      directory,
      {
        mode: "lite",
        source: "test",
        sessionId: "ses-test-2",
        activatedAt: nowIso(),
        updatedAt: nowIso(),
      },
      { lastUpdatedAt: nowIso() },
    )

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

test("state mutations refuse malformed existing JSON without replacement", () => {
  withTempDir((directory) => {
    const path = resolveGatewayStatePath(directory)
    mkdirSync(join(directory, ".opencode"), { recursive: true })
    writeFileSync(path, "{not-json}\n", "utf-8")

    const before = readFileSync(path)
    assert.throws(
      () =>
        saveGatewayConciseMode(
          directory,
          {
            mode: "review",
            source: "test",
            sessionId: "ses-test-3",
            activatedAt: nowIso(),
            updatedAt: nowIso(),
          },
          { lastUpdatedAt: nowIso(), source: "write" },
        ),
      (error) =>
        error instanceof GatewayStateProtocolError && error.reasonCode === "gateway_state_malformed_json",
    )
    assert.deepEqual(readFileSync(path), before)
  })
})

test("loadGatewayState drops legacy concise mode entries without session id", () => {
  withTempDir((directory) => {
    saveGatewayState(directory, {
      activeLoop: null,
      lastUpdatedAt: nowIso(),
    })
    saveGatewayConciseMode(
      directory,
      {
        mode: "full",
        source: "legacy",
        sessionId: "",
        activatedAt: nowIso(),
        updatedAt: nowIso(),
      },
      { lastUpdatedAt: nowIso() },
    )
    const state = loadGatewayState(directory)
    assert.equal(state?.conciseMode, null)
  })
})

test("loadGatewayState reloads external concise mode changes after cache warmup", () => {
  withTempDir((directory) => {
    saveGatewayState(directory, {
      activeLoop: null,
      lastUpdatedAt: nowIso(),
    })
    saveGatewayConciseMode(
      directory,
      {
        mode: "lite",
        source: "initial",
        sessionId: "ses-initial",
        activatedAt: nowIso(),
        updatedAt: nowIso(),
      },
      { lastUpdatedAt: nowIso() },
    )
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

test("first write is private and leaves no lock or stage", () => {
  withTempDir((directory) => {
    const result = saveGatewayState(directory, {
      activeLoop: null,
      lastUpdatedAt: nowIso(),
    })
    const stateDirectory = join(directory, ".opencode")
    const statePath = resolveGatewayStatePath(directory)
    assert.equal(lstatSync(stateDirectory).mode & 0o777, PRIVATE_DIRECTORY_MODE)
    assert.equal(lstatSync(statePath).mode & 0o777, PRIVATE_FILE_MODE)
    assert.equal(result.committed, true)
    assert.equal(result.durability, "synced")
    assert.equal(result.lockReleased, true)
    assert.equal(readdirSync(stateDirectory).some((name) => name.startsWith(STAGE_PREFIX)), false)
    assert.equal(readdirSync(stateDirectory).includes(LOCK_DIRECTORY_NAME), false)
  })
})

test("one-domain writes preserve sibling and unknown root/nested fields", () => {
  withTempDir((directory) => {
    const path = seedRawState(directory)
    const state = loadGatewayState(directory)
    assert.ok(state?.activeLoop)
    state.activeLoop.active = false
    state.activeLoop.sessionId = "updated"
    state.lastUpdatedAt = nowIso()
    state.source = "active-writer"
    saveGatewayState(directory, state)

    saveGatewayConciseMode(
      directory,
      {
        mode: "full",
        source: "concise-writer",
        sessionId: "updated-concise",
        activatedAt: nowIso(),
        updatedAt: nowIso(),
      },
      { lastUpdatedAt: nowIso() },
    )
    const raw = JSON.parse(readFileSync(path, "utf-8"))
    assert.equal(raw.activeLoop.sessionId, "updated")
    assert.equal(raw.activeLoop.unknownLoop.sentinel, "loop")
    assert.equal(raw.conciseMode.mode, "full")
    assert.equal(raw.conciseMode.unknownConcise.sentinel, "concise")
    assert.equal(raw.unknownRoot.sentinel, "root")
  })
})

test("prototype-sensitive unknown keys remain inert own JSON properties", () => {
  withTempDir((directory) => {
    const stateDirectory = join(directory, ".opencode")
    mkdirSync(stateDirectory, { mode: PRIVATE_DIRECTORY_MODE })
    const path = resolveGatewayStatePath(directory)
    writeFileSync(
      path,
      '{"activeLoop":null,"lastUpdatedAt":"2026-07-27T00:00:00Z","__proto__":{"polluted":true}}\n',
      { mode: PRIVATE_FILE_MODE },
    )
    updateGatewayStateDomain(
      directory,
      "conciseMode",
      {
        mode: "lite",
        source: "test",
        sessionId: "session",
        activatedAt: nowIso(),
        updatedAt: nowIso(),
      },
      { rootUpdates: { lastUpdatedAt: nowIso() } },
    )
    const raw = JSON.parse(readFileSync(path, "utf-8"))
    assert.equal(Object.hasOwn(raw, "__proto__"), true)
    assert.equal(raw.__proto__.polluted, true)
    assert.equal({}.polluted, undefined)
  })
})

test("loaded active state refuses to overwrite a concurrent active update", () => {
  withTempDir((directory) => {
    seedRawState(directory)
    const stale = loadGatewayState(directory)
    assert.ok(stale?.activeLoop)
    updateGatewayStateDomain(
      directory,
      "activeLoop",
      { sessionId: "newer" },
      { mode: "patch", rootUpdates: { lastUpdatedAt: nowIso() } },
    )
    stale.activeLoop.sessionId = "stale"
    assert.throws(
      () => saveGatewayState(directory, stale),
      (error) =>
        error instanceof GatewayStateProtocolError && error.reasonCode === "gateway_state_target_changed",
    )
    assert.equal(loadGatewayState(directory)?.activeLoop?.sessionId, "newer")
  })
})

test("open reader accepts atomic replacement of its opened inode", () => {
  withTempDir((directory) => {
    const path = seedRawState(directory)
    const replacement = JSON.parse(readFileSync(path, "utf-8"))
    replacement.activeLoop.sessionId = "replacement"
    const observed = loadRawGatewayState(directory, {
      failureInjector(phase) {
        if (phase !== "after_state_open") return
        const replacementPath = join(directory, ".opencode", "replacement.json")
        writeFileSync(replacementPath, `${JSON.stringify(replacement, null, 2)}\n`, {
          mode: PRIVATE_FILE_MODE,
        })
        renameSync(replacementPath, path)
      },
    })
    assert.equal(observed.activeLoop.sessionId, "seed")
    assert.equal(loadGatewayState(directory)?.activeLoop?.sessionId, "replacement")
  })
})

test("typed state normalization rejects malformed active-loop schema", () => {
  withTempDir((directory) => {
    const path = seedRawState(directory)
    const malformed = JSON.parse(readFileSync(path, "utf-8"))
    malformed.activeLoop.completionPromise = { invalid: true }
    writeFileSync(path, `${JSON.stringify(malformed, null, 2)}\n`, { mode: PRIVATE_FILE_MODE })
    assert.equal(loadGatewayState(directory)?.activeLoop, null)
  })
})

test("unsafe ancestor namespace is rejected", () => {
  withTempDir((directory) => {
    const unsafeParent = join(directory, "unsafe-parent")
    mkdirSync(unsafeParent)
    chmodSync(unsafeParent, 0o777)
    const project = join(unsafeParent, "project")
    mkdirSync(project, { mode: PRIVATE_DIRECTORY_MODE })
    assert.throws(
      () => loadGatewayState(project),
      (error) =>
        error instanceof GatewayStateProtocolError &&
        error.reasonCode === "gateway_state_unsafe_project_root",
    )
    assert.equal(lstatSync(project).isDirectory(), true)
  })
})

test("nonfinite lock timeouts are rejected before mutation", () => {
  for (const timeoutMs of [Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY]) {
    withTempDir((directory) => {
      assert.throws(
        () => updateGatewayStateDomain(directory, "activeLoop", null, {}, { timeoutMs }),
        (error) =>
          error instanceof GatewayStateProtocolError &&
          error.reasonCode === "gateway_state_invalid_timeout",
      )
      assert.equal(readdirSync(directory).includes(".opencode"), false)
    })
  }
})

test("fixed state path rejects overrides", () => {
  withTempDir((directory) => {
    assert.throws(
      () => resolveGatewayStatePath(directory, "../victim.json"),
      (error) =>
        error instanceof GatewayStateProtocolError && error.reasonCode === "gateway_state_unsafe_target",
    )
  })
})

test("invalid UTF-8, non-object roots, and unsafe numbers fail closed", () => {
  const cases = [
    [Buffer.from([0x7b, 0x22, 0x78, 0x22, 0x3a, 0xff, 0x7d]), "gateway_state_invalid_utf8"],
    [Buffer.from("[]\n"), "gateway_state_root_not_object"],
    [Buffer.from('{"value":9007199254740993}\n'), "gateway_state_number_unsupported"],
    [Buffer.from('{"value":1e999}\n'), "gateway_state_number_unsupported"],
  ]
  for (const [content, reasonCode] of cases) {
    withTempDir((directory) => {
      const stateDirectory = join(directory, ".opencode")
      mkdirSync(stateDirectory, { mode: PRIVATE_DIRECTORY_MODE })
      const path = resolveGatewayStatePath(directory)
      writeFileSync(path, content, { mode: PRIVATE_FILE_MODE })
      chmodSync(path, PRIVATE_FILE_MODE)
      const before = readFileSync(path)
      assert.throws(
        () => updateGatewayStateDomain(directory, "activeLoop", null),
        (error) => error instanceof GatewayStateProtocolError && error.reasonCode === reasonCode,
      )
      assert.deepEqual(readFileSync(path), before)
      assert.equal(readdirSync(stateDirectory).includes(LOCK_DIRECTORY_NAME), false)
    })
  }
})

test("symlink, hardlink, special target, and unsafe parent attacks preserve victims", () => {
  withTempDir((directory) => {
    const victimDirectory = join(directory, "victim-directory")
    mkdirSync(victimDirectory)
    const victim = join(victimDirectory, "keep.json")
    writeFileSync(victim, '{"victim":true}\n')
    symlinkSync(victimDirectory, join(directory, ".opencode"), "dir")
    const before = readFileSync(victim)
    assert.throws(
      () => updateGatewayStateDomain(directory, "activeLoop", null),
      (error) =>
        error instanceof GatewayStateProtocolError && error.reasonCode === "gateway_state_unsafe_directory",
    )
    assert.deepEqual(readFileSync(victim), before)
  })

  for (const attack of ["symlink", "hardlink", "directory"]) {
    withTempDir((directory) => {
      const stateDirectory = join(directory, ".opencode")
      mkdirSync(stateDirectory, { mode: PRIVATE_DIRECTORY_MODE })
      const target = resolveGatewayStatePath(directory)
      const victim = join(directory, "victim.json")
      writeFileSync(victim, '{"victim":true}\n')
      if (attack === "symlink") {
        symlinkSync(victim, target)
      } else if (attack === "hardlink") {
        linkSync(victim, target)
      } else {
        mkdirSync(target)
      }
      const before = readFileSync(victim)
      assert.throws(
        () => updateGatewayStateDomain(directory, "activeLoop", null),
        (error) =>
          error instanceof GatewayStateProtocolError && error.reasonCode === "gateway_state_unsafe_target",
      )
      assert.deepEqual(readFileSync(victim), before)
    })
  }

  withTempDir((directory) => {
    const stateDirectory = join(directory, ".opencode")
    mkdirSync(stateDirectory, { mode: PRIVATE_DIRECTORY_MODE })
    chmodSync(stateDirectory, 0o777)
    assert.throws(
      () => updateGatewayStateDomain(directory, "activeLoop", null),
      (error) =>
        error instanceof GatewayStateProtocolError && error.reasonCode === "gateway_state_unsafe_directory",
    )
  })
})

test("valid and incomplete locks time out without reclamation", () => {
  for (const tokenContent of [`${"a".repeat(64)}\n`, "partial"]) {
    withTempDir((directory) => {
      const stateDirectory = join(directory, ".opencode")
      const lock = join(stateDirectory, LOCK_DIRECTORY_NAME)
      mkdirSync(lock, { recursive: true, mode: PRIVATE_DIRECTORY_MODE })
      chmodSync(lock, PRIVATE_DIRECTORY_MODE)
      const token = join(lock, OWNER_TOKEN_NAME)
      writeFileSync(token, tokenContent, { mode: PRIVATE_FILE_MODE })
      chmodSync(token, PRIVATE_FILE_MODE)
      const started = performance.now()
      assert.throws(
        () =>
          updateGatewayStateDomain(
            directory,
            "activeLoop",
            null,
            {},
            { timeoutMs: 60 },
          ),
        (error) =>
          error instanceof GatewayStateProtocolError && error.reasonCode === "gateway_state_lock_timeout",
      )
      assert.ok(performance.now() - started >= 40)
      assert.ok(performance.now() - started < 500)
      assert.equal(readFileSync(token, "utf-8"), tokenContent)
      const status = gatewayStateLockStatus(directory)
      assert.equal(status.present, true)
      assert.equal(status.recovery_guidance, LOCK_RECOVERY_GUIDANCE)
    })
  }
})

test("stable unsafe lock tokens fail immediately without mutation", () => {
  const cases = [
    {
      name: "world-readable",
      setup(ownerPath) {
        writeFileSync(ownerPath, `${"a".repeat(64)}\n`, { mode: 0o644 })
        chmodSync(ownerPath, 0o644)
      },
    },
    {
      name: "symlink",
      setup(ownerPath, stateDirectory) {
        const victim = join(stateDirectory, "owner-victim-symlink")
        writeFileSync(victim, `${"a".repeat(64)}\n`, { mode: PRIVATE_FILE_MODE })
        symlinkSync(victim, ownerPath)
      },
    },
    {
      name: "hardlink",
      setup(ownerPath, stateDirectory) {
        const victim = join(stateDirectory, "owner-victim-hardlink")
        writeFileSync(victim, `${"a".repeat(64)}\n`, { mode: PRIVATE_FILE_MODE })
        linkSync(victim, ownerPath)
      },
    },
    {
      name: "directory",
      setup(ownerPath) {
        mkdirSync(ownerPath, { mode: PRIVATE_DIRECTORY_MODE })
      },
    },
    {
      name: "oversized",
      setup(ownerPath) {
        writeFileSync(ownerPath, "a".repeat(66), { mode: PRIVATE_FILE_MODE })
      },
    },
    {
      name: "malformed",
      setup(ownerPath) {
        writeFileSync(ownerPath, `${"g".repeat(64)}\n`, { mode: PRIVATE_FILE_MODE })
      },
    },
  ]

  for (const fixture of cases) {
    withTempDir((directory) => {
      const statePath = seedRawState(directory)
      const stateBefore = readFileSync(statePath)
      const stateDirectory = join(directory, ".opencode")
      const lock = join(stateDirectory, LOCK_DIRECTORY_NAME)
      mkdirSync(lock, { mode: PRIVATE_DIRECTORY_MODE })
      chmodSync(lock, PRIVATE_DIRECTORY_MODE)
      const ownerPath = join(lock, OWNER_TOKEN_NAME)
      fixture.setup(ownerPath, stateDirectory)
      const lockBefore = lockNodeSnapshot(lock)
      const ownerBefore = lockNodeSnapshot(ownerPath)
      const started = performance.now()
      assert.throws(
        () =>
          updateGatewayStateDomain(directory, "activeLoop", null, {}, { timeoutMs: 500 }),
        (error) =>
          error instanceof GatewayStateProtocolError &&
          error.reasonCode === "gateway_state_lock_unsafe",
        fixture.name,
      )
      assert.ok(performance.now() - started < 300, fixture.name)
      assert.deepEqual(lockNodeSnapshot(lock), lockBefore, fixture.name)
      assert.deepEqual(lockNodeSnapshot(ownerPath), ownerBefore, fixture.name)
      assert.deepEqual(readFileSync(statePath), stateBefore, fixture.name)
    })
  }
})

test("unsafe token metadata from a replaced lock generation retries", () => {
  withTempDir((directory) => {
    const statePath = seedRawState(directory)
    const stateBefore = readFileSync(statePath)
    const lock = join(directory, ".opencode", LOCK_DIRECTORY_NAME)
    mkdirSync(lock, { mode: PRIVATE_DIRECTORY_MODE })
    chmodSync(lock, PRIVATE_DIRECTORY_MODE)
    const ownerPath = join(lock, OWNER_TOKEN_NAME)
    writeFileSync(ownerPath, `${"a".repeat(64)}\n`, { mode: 0o644 })
    chmodSync(ownerPath, 0o644)
    let confirmationCount = 0
    let replacement

    assert.throws(
      () =>
        updateGatewayStateDomain(
          directory,
          "activeLoop",
          null,
          {},
          {
            timeoutMs: 80,
            failureInjector(phase) {
              if (phase !== "before_lock_token_unsafe_confirmation") return
              confirmationCount += 1
              if (confirmationCount === 1) {
                replacement = replaceLockGeneration(lock, PRIVATE_FILE_MODE)
              }
            },
          },
        ),
      (error) =>
        error instanceof GatewayStateProtocolError &&
        error.reasonCode === "gateway_state_lock_timeout",
    )
    assert.equal(confirmationCount, 1)
    assert.ok(replacement)
    assert.deepEqual(lockNodeSnapshot(lock), replacement.lock)
    assert.deepEqual(lockNodeSnapshot(join(lock, OWNER_TOKEN_NAME)), replacement.owner)
    assert.deepEqual(readFileSync(statePath), stateBefore)
    assert.equal(lstatSync(replacement.displaced).isDirectory(), true)
  })
})

test("an unsafe replacement generation retries once then fails closed", () => {
  withTempDir((directory) => {
    const statePath = seedRawState(directory)
    const stateBefore = readFileSync(statePath)
    const lock = join(directory, ".opencode", LOCK_DIRECTORY_NAME)
    mkdirSync(lock, { mode: PRIVATE_DIRECTORY_MODE })
    chmodSync(lock, PRIVATE_DIRECTORY_MODE)
    const ownerPath = join(lock, OWNER_TOKEN_NAME)
    writeFileSync(ownerPath, `${"a".repeat(64)}\n`, { mode: 0o644 })
    chmodSync(ownerPath, 0o644)
    let confirmationCount = 0
    let replacement

    assert.throws(
      () =>
        updateGatewayStateDomain(
          directory,
          "activeLoop",
          null,
          {},
          {
            timeoutMs: 500,
            failureInjector(phase) {
              if (phase !== "before_lock_token_unsafe_confirmation") return
              confirmationCount += 1
              if (confirmationCount === 1) {
                replacement = replaceLockGeneration(lock, 0o644)
              }
            },
          },
        ),
      (error) =>
        error instanceof GatewayStateProtocolError &&
        error.reasonCode === "gateway_state_lock_unsafe",
    )
    assert.equal(confirmationCount, 2)
    assert.ok(replacement)
    assert.deepEqual(lockNodeSnapshot(lock), replacement.lock)
    assert.deepEqual(lockNodeSnapshot(join(lock, OWNER_TOKEN_NAME)), replacement.owner)
    assert.deepEqual(readFileSync(statePath), stateBefore)
    assert.equal(lstatSync(replacement.displaced).isDirectory(), true)
  })
})

test("nested state transaction fails reentrant without waiting", () => {
  withTempDir((directory) => {
    const started = performance.now()
    assert.throws(
      () =>
        transactGatewayStateDomain(directory, "activeLoop", () => {
          updateGatewayStateDomain(directory, "conciseMode", null)
          return { value: null }
        }),
      (error) =>
        error instanceof GatewayStateProtocolError && error.reasonCode === "gateway_state_lock_reentrant",
    )
    assert.ok(performance.now() - started < 500)
    assert.equal(readdirSync(join(directory, ".opencode")).includes(LOCK_DIRECTORY_NAME), false)
  })
})

test("failure injection distinguishes pre-commit and post-commit outcomes", () => {
  withTempDir((directory) => {
    const path = seedRawState(directory)
    const before = readFileSync(path)
    assert.throws(
      () =>
        updateGatewayStateDomain(
          directory,
          "activeLoop",
          { active: false },
          { mode: "patch" },
          {
            failureInjector(phase) {
              if (phase === "after_stage_fsync") throw new Error("pre-commit")
            },
          },
        ),
      (error) =>
        error instanceof GatewayStateProtocolError &&
        error.reasonCode === "gateway_state_io_failed" &&
        error.committed === false,
    )
    assert.deepEqual(readFileSync(path), before)
    assert.equal(readdirSync(join(directory, ".opencode")).some((name) => name.startsWith(STAGE_PREFIX)), false)

    assert.throws(
      () =>
        updateGatewayStateDomain(
          directory,
          "activeLoop",
          { active: false },
          { mode: "patch" },
          {
            failureInjector(phase) {
              if (phase === "after_replace") throw new Error("post-commit")
            },
          },
        ),
      (error) =>
        error instanceof GatewayStateProtocolError &&
        error.reasonCode === "committed_durability_uncertain" &&
        error.committed === true &&
        error.lockReleased === true,
    )
    assert.equal(loadGatewayState(directory)?.activeLoop?.active, false)
  })
})

test("lock identity replacement is never deleted during release", () => {
  withTempDir((directory) => {
    seedRawState(directory)
    const lock = join(directory, ".opencode", LOCK_DIRECTORY_NAME)
    const displaced = `${lock}.owned`
    assert.throws(
      () =>
        updateGatewayStateDomain(
          directory,
          "activeLoop",
          { active: false },
          { mode: "patch" },
          {
            failureInjector(phase) {
              if (phase !== "before_lock_release") return
              renameSync(lock, displaced)
              mkdirSync(lock, { mode: PRIVATE_DIRECTORY_MODE })
              const token = join(lock, OWNER_TOKEN_NAME)
              writeFileSync(token, `${"b".repeat(64)}\n`, { mode: PRIVATE_FILE_MODE })
              chmodSync(token, PRIVATE_FILE_MODE)
            },
          },
        ),
      (error) =>
        error instanceof GatewayStateProtocolError &&
        error.reasonCode === "committed_lock_release_failed" &&
        error.committed === true,
    )
    assert.equal(readFileSync(join(lock, OWNER_TOKEN_NAME), "utf-8"), `${"b".repeat(64)}\n`)
  })
})

test("lock release metadata tracks owned-lock disposition", () => {
  withTempDir((directory) => {
    seedRawState(directory)
    const lock = join(directory, ".opencode", LOCK_DIRECTORY_NAME)
    assert.throws(
      () =>
        updateGatewayStateDomain(
          directory,
          "activeLoop",
          { active: false },
          { mode: "patch" },
          {
            failureInjector(phase) {
              if (phase === "before_lock_release") throw new Error("before remove")
            },
          },
        ),
      (error) =>
        error instanceof GatewayStateProtocolError &&
        error.reasonCode === "committed_lock_release_failed" &&
        error.lockReleased === false,
    )
    assert.equal(lstatSync(lock).isDirectory(), true)
  })

  withTempDir((directory) => {
    seedRawState(directory)
    const lock = join(directory, ".opencode", LOCK_DIRECTORY_NAME)
    assert.throws(
      () =>
        updateGatewayStateDomain(
          directory,
          "activeLoop",
          { active: false },
          { mode: "patch" },
          {
            failureInjector(phase) {
              if (phase === "after_lock_remove") throw new Error("after remove")
            },
          },
        ),
      (error) =>
        error instanceof GatewayStateProtocolError &&
        error.reasonCode === "committed_lock_release_failed" &&
        error.lockReleased === true,
    )
    assert.equal(readdirSync(join(directory, ".opencode")).includes(LOCK_DIRECTORY_NAME), false)
  })
})

test("two Node writers preserve disjoint domains while readers observe valid JSON", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-core-concurrency-"))
  try {
    const path = seedRawState(directory)
    let settled = false
    const writers = Promise.all([
      runWriter(directory, "activeLoop"),
      runWriter(directory, "conciseMode"),
    ]).finally(() => {
      settled = true
    })
    const deadline = performance.now() + 15_000
    let observations = 0
    while (!settled) {
      assert.ok(performance.now() < deadline)
      const payload = loadGatewayState(directory)
      assert.equal(typeof payload, "object")
      observations += 1
      await new Promise((resolve) => setTimeout(resolve, 2))
    }
    const reports = await writers
    assert.deepEqual(
      new Set(reports.map((item) => item.domain)),
      new Set(["activeLoop", "conciseMode"]),
    )
    assert.ok(observations > 0)
    const final = JSON.parse(readFileSync(path, "utf-8"))
    assert.equal(final.activeLoop.unknownLoop.sentinel, "loop")
    assert.equal(final.conciseMode.unknownConcise.sentinel, "concise")
    assert.equal(final.unknownRoot.sentinel, "root")
    const entries = readdirSync(join(directory, ".opencode"))
    assert.equal(entries.includes(LOCK_DIRECTORY_NAME), false)
    assert.equal(entries.some((name) => name.startsWith(STAGE_PREFIX)), false)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
