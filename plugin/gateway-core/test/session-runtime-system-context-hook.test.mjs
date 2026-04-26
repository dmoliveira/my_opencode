import assert from "node:assert/strict"
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"
import { createSessionRuntimeSystemContextHook } from "../dist/hooks/session-runtime-system-context/index.js"
import { saveGatewayState, nowIso } from "../dist/state/storage.js"

test("session-runtime-system-context injects hidden system session id", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-session-runtime-system-"))
  try {
    const hook = createSessionRuntimeSystemContextHook({ directory, enabled: true, conciseModeEnabled: false, conciseDefaultMode: "off" })
    const output = { system: ["existing system"] }
    await hook.event("experimental.chat.system.transform", {
      input: { sessionID: "session-hidden-1" },
      output,
      directory,
    })
    assert.match(output.system[0], /runtime_session_context: session-hidden-1/)
    assert.equal(output.system[1], "existing system")
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("session-runtime-system-context dedupes hidden system session id", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-session-runtime-system-"))
  try {
    const hook = createSessionRuntimeSystemContextHook({ directory, enabled: true, conciseModeEnabled: false, conciseDefaultMode: "off" })
    const output = { system: ["existing system"] }
    await hook.event("experimental.chat.system.transform", {
      input: { sessionID: "session-hidden-2" },
      output,
      directory,
    })
    await hook.event("experimental.chat.system.transform", {
      input: { sessionID: "session-hidden-2" },
      output,
      directory,
    })
    assert.equal(output.system.filter((line) => line.includes('runtime_session_context:')).length, 1)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("session-runtime-system-context replaces stale hidden system session id", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-session-runtime-system-"))
  try {
    const hook = createSessionRuntimeSystemContextHook({ directory, enabled: true, conciseModeEnabled: false, conciseDefaultMode: "off" })
    const output = { system: ["runtime_session_context: stale-session\nUse this exact runtime session id for commits, logs, telemetry, and external tooling created during this session."] }
    await hook.event("experimental.chat.system.transform", {
      input: { sessionID: "session-hidden-3" },
      output,
      directory,
    })
    assert.equal(output.system.filter((line) => line.includes("runtime_session_context:")).length, 1)
    assert.match(output.system[0], /runtime_session_context: session-hidden-3/)
    assert.doesNotMatch(output.system[0], /stale-session/)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("session-runtime-system-context integrates through plugin system transform", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-session-runtime-system-"))
  try {
    const plugin = GatewayCorePlugin({ directory })
    const output = { system: ["baseline"] }
    await plugin["experimental.chat.system.transform"](
      { sessionID: "session-hidden-plugin", model: { providerID: "openai", modelID: "gpt-5" } },
      output,
    )
    assert.match(output.system[0], /runtime_session_context: session-hidden-plugin/)
    assert.equal(output.system.includes("baseline"), true)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("session-runtime-system-context injects active concise mode from gateway state", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-session-runtime-system-"))
  try {
    mkdirSync(join(directory, "skills", "concise-mode"), { recursive: true })
    writeFileSync(
      join(directory, "skills", "concise-mode", "SKILL.md"),
      "---\nname: concise-mode\n---\nRespond terse. Keep technical terms exact.\n",
      "utf-8",
    )
    saveGatewayState(directory, {
      activeLoop: null,
      conciseMode: {
        mode: "full",
        source: "test",
        sessionId: "session-hidden-4",
        activatedAt: nowIso(),
        updatedAt: nowIso(),
      },
      lastUpdatedAt: nowIso(),
    })
    const hook = createSessionRuntimeSystemContextHook({ directory, enabled: true, conciseModeEnabled: false, conciseDefaultMode: "off" })
    const output = { system: ["baseline"] }
    await hook.event("experimental.chat.system.transform", {
      input: { sessionID: "session-hidden-4" },
      output,
      directory,
    })
    assert.match(output.system[0], /runtime_concise_mode: full/)
    assert.match(output.system[0], /Respond terse\. Keep technical terms exact\./)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("session-runtime-system-context ignores concise mode from a different session", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-session-runtime-system-"))
  try {
    saveGatewayState(directory, {
      activeLoop: null,
      conciseMode: {
        mode: "review",
        source: "test",
        sessionId: "session-other",
        activatedAt: nowIso(),
        updatedAt: nowIso(),
      },
      lastUpdatedAt: nowIso(),
    })
    const hook = createSessionRuntimeSystemContextHook({ directory, enabled: true, conciseModeEnabled: false, conciseDefaultMode: "off" })
    const output = { system: ["baseline"] }
    await hook.event("experimental.chat.system.transform", {
      input: { sessionID: "session-hidden-5" },
      output,
      directory,
    })
    assert.equal(output.system.some((line) => line.includes("runtime_concise_mode:")), false)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
