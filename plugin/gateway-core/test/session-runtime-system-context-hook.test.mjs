import assert from "node:assert/strict"
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import { gatewayEventAuditPath } from "../dist/audit/event-audit.js"
import GatewayCorePlugin from "../dist/index.js"
import { createSessionRuntimeSystemContextHook, stablePromptFingerprint } from "../dist/hooks/session-runtime-system-context/index.js"
import { saveGatewayConciseMode, nowIso } from "../dist/state/storage.js"

function saveConciseState(directory, conciseMode) {
  saveGatewayConciseMode(directory, conciseMode, { lastUpdatedAt: nowIso() })
}

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
    assert.match(output.system.join("\n"), /runtime_session_context: session-hidden-1/)
    assert.equal(output.system[0], "existing system")
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("session-runtime-system-context dedupes hidden system session id", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-session-runtime-system-"))
  try {
    const hook = createSessionRuntimeSystemContextHook({ directory, enabled: true, injectSessionIdContext: true, conciseModeEnabled: false, conciseDefaultMode: "off" })
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

test("session-runtime-system-context audits only changed no-concise transforms", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-session-runtime-system-"))
  const previousAudit = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
  process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = "1"
  try {
    const hook = createSessionRuntimeSystemContextHook({ directory, enabled: true, injectSessionIdContext: true, conciseModeEnabled: false, conciseDefaultMode: "off" })
    const output = { system: ["baseline"] }
    await hook.event("experimental.chat.system.transform", {
      input: { sessionID: "session-hidden-audit-1" },
      output,
      directory,
    })
    await hook.event("experimental.chat.system.transform", {
      input: { sessionID: "session-hidden-audit-1" },
      output,
      directory,
    })

    const auditLines = readFileSync(gatewayEventAuditPath(directory), "utf8")
      .trim()
      .split("\n")
      .filter(Boolean)
      .map((line) => JSON.parse(line))
      .filter((entry) => entry.hook === "session-runtime-system-context")

    assert.equal(auditLines.length, 1)
    assert.equal(auditLines[0]?.reason_code, "session_runtime_context_injected_without_concise_mode")
  } finally {
    if (previousAudit === undefined) {
      delete process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
    } else {
      process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = previousAudit
    }
    rmSync(directory, { recursive: true, force: true })
  }
})

test("session-runtime-system-context replaces stale hidden system session id", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-session-runtime-system-"))
  try {
    const hook = createSessionRuntimeSystemContextHook({ directory, enabled: true, injectSessionIdContext: true, conciseModeEnabled: false, conciseDefaultMode: "off" })
    const output = { system: ["runtime_session_context: stale-session\nUse this exact runtime session id for commits, logs, telemetry, and external tooling created during this session."] }
    await hook.event("experimental.chat.system.transform", {
      input: { sessionID: "session-hidden-3" },
      output,
      directory,
    })
    assert.equal(output.system.filter((line) => line.includes("runtime_session_context:")).length, 1)
    assert.match(output.system.join("\n"), /runtime_session_context: session-hidden-3/)
    assert.doesNotMatch(output.system.join("\n"), /stale-session/)
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
    assert.match(output.system.join("\n"), /runtime_session_context: session-hidden-plugin/)
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
    saveConciseState(directory, {
        mode: "full",
        source: "test",
        sessionId: "session-hidden-4",
        activatedAt: nowIso(),
        updatedAt: nowIso(),
    })
    const hook = createSessionRuntimeSystemContextHook({ directory, enabled: true, injectSessionIdContext: true, conciseModeEnabled: false, conciseDefaultMode: "off" })
    const output = { system: ["baseline"] }
    await hook.event("experimental.chat.system.transform", {
      input: { sessionID: "session-hidden-4" },
      output,
      directory,
    })
    assert.match(output.system.join("\n"), /runtime_concise_mode: full/)
    assert.match(output.system.join("\n"), /Respond terse\. Keep technical terms exact\./)
    assert.ok(
      output.system.findIndex((line) => line.startsWith("runtime_concise_mode:")) <
        output.system.findIndex((line) => line.startsWith("runtime_session_context:")),
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("session-runtime-system-context reloads changed concise skill body on later transforms", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-session-runtime-system-"))
  try {
    mkdirSync(join(directory, "skills", "concise-mode"), { recursive: true })
    const skillPath = join(directory, "skills", "concise-mode", "SKILL.md")
    writeFileSync(skillPath, "---\nname: concise-mode\n---\nFirst concise rules.\n", "utf-8")
    saveConciseState(directory, {
        mode: "full",
        source: "test",
        sessionId: "session-hidden-4b",
        activatedAt: nowIso(),
        updatedAt: nowIso(),
    })
    const hook = createSessionRuntimeSystemContextHook({ directory, enabled: true, injectSessionIdContext: true, conciseModeEnabled: false, conciseDefaultMode: "off" })
    const first = { system: ["baseline"] }
    await hook.event("experimental.chat.system.transform", {
      input: { sessionID: "session-hidden-4b" },
      output: first,
      directory,
    })
    assert.match(first.system.join("\n"), /First concise rules\./)

    writeFileSync(skillPath, "---\nname: concise-mode\n---\nSecond concise rules are now longer.\n", "utf-8")
    const second = { system: ["baseline"] }
    await hook.event("experimental.chat.system.transform", {
      input: { sessionID: "session-hidden-4b" },
      output: second,
      directory,
    })
    assert.match(second.system.join("\n"), /Second concise rules are now longer\./)
    assert.doesNotMatch(second.system.join("\n"), /First concise rules\./)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("session-runtime-system-context ignores concise mode from a different session", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-session-runtime-system-"))
  try {
    saveConciseState(directory, {
        mode: "review",
        source: "test",
        sessionId: "session-other",
        activatedAt: nowIso(),
        updatedAt: nowIso(),
    })
    const hook = createSessionRuntimeSystemContextHook({ directory, enabled: true, injectSessionIdContext: true, conciseModeEnabled: false, conciseDefaultMode: "off" })
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

test("session-runtime-system-context can scope session id injection to concise mode only", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-session-runtime-system-"))
  try {
    const hook = createSessionRuntimeSystemContextHook({
      directory,
      enabled: true,
      injectSessionIdContext: true,
      injectSessionIdWhenConciseModeOnly: true,
      conciseModeEnabled: false,
      conciseDefaultMode: "off",
    })
    const output = { system: ["baseline"] }
    await hook.event("experimental.chat.system.transform", {
      input: { sessionID: "session-hidden-6" },
      output,
      directory,
    })
    assert.equal(output.system.some((line) => line.includes("runtime_session_context:")), false)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("session-runtime-system-context audits stale context removal under concise-only scope", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-session-runtime-system-"))
  const previousAudit = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
  process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = "1"
  try {
    const hook = createSessionRuntimeSystemContextHook({
      directory,
      enabled: true,
      injectSessionIdContext: true,
      injectSessionIdWhenConciseModeOnly: true,
      conciseModeEnabled: false,
      conciseDefaultMode: "off",
    })
    const output = {
      system: [
        "runtime_session_context: stale-session\nUse this exact runtime session id for commits, logs, telemetry, and external tooling created during this session.",
        "baseline",
      ],
    }
    await hook.event("experimental.chat.system.transform", {
      input: { sessionID: "session-hidden-6b" },
      output,
      directory,
    })

    assert.equal(output.system.some((line) => line.includes("runtime_session_context:")), false)

    const auditLines = readFileSync(gatewayEventAuditPath(directory), "utf8")
      .trim()
      .split("\n")
      .filter(Boolean)
      .map((line) => JSON.parse(line))
      .filter((entry) => entry.hook === "session-runtime-system-context")

    assert.equal(auditLines.length, 1)
    assert.equal(auditLines[0]?.reason_code, "session_runtime_context_skipped_by_concise_scope")
  } finally {
    if (previousAudit === undefined) {
      delete process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
    } else {
      process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = previousAudit
    }
    rmSync(directory, { recursive: true, force: true })
  }
})

test("session-runtime-system-context concise-only scope injects when concise is active", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-session-runtime-system-"))
  try {
    saveConciseState(directory, {
        mode: "lite",
        source: "test",
        sessionId: "session-hidden-7",
        activatedAt: nowIso(),
        updatedAt: nowIso(),
    })
    const hook = createSessionRuntimeSystemContextHook({
      directory,
      enabled: true,
      injectSessionIdContext: true,
      injectSessionIdWhenConciseModeOnly: true,
      conciseModeEnabled: false,
      conciseDefaultMode: "off",
    })
    const output = { system: ["baseline"] }
    await hook.event("experimental.chat.system.transform", {
      input: { sessionID: "session-hidden-7" },
      output,
      directory,
    })
    assert.match(output.system.join("\n"), /runtime_concise_mode: lite/)
    assert.ok(output.system.some((line) => line.includes("runtime_session_context: session-hidden-7")))
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})


test("session-runtime-system-context repairs managed block order without touching marker mentions", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-session-runtime-system-"))
  try {
    const hook = createSessionRuntimeSystemContextHook({
      directory,
      enabled: true,
      injectSessionIdContext: true,
      conciseModeEnabled: true,
      conciseDefaultMode: "lite",
    })
    const markerMention = "Unmanaged guidance\nmentions runtime_session_context: only as prose."
    const output = {
      system: [
        "baseline",
        "runtime_session_context: stale-one",
        markerMention,
        "runtime_concise_mode: stale",
        "runtime_session_context: stale-two",
      ],
    }
    await hook.event("experimental.chat.system.transform", {
      input: { sessionID: "session-order-repair" },
      output,
      directory,
    })

    assert.equal(output.system[0], "baseline")
    assert.equal(output.system[1], markerMention)
    assert.equal(output.system.filter((line) => line.startsWith("runtime_concise_mode:")).length, 1)
    assert.equal(output.system.filter((line) => line.startsWith("runtime_session_context:")).length, 1)
    assert.equal(output.system.at(-2).startsWith("runtime_concise_mode: lite"), true)
    assert.equal(output.system.at(-1).startsWith("runtime_session_context: session-order-repair"), true)

    output.system.push("late stable guidance")
    await hook.event("experimental.chat.system.transform", {
      input: { sessionID: "session-order-repair" },
      output,
      directory,
    })
    assert.equal(output.system.at(-3), "late stable guidance")
    assert.equal(output.system.at(-2).startsWith("runtime_concise_mode: lite"), true)
    assert.equal(output.system.at(-1).startsWith("runtime_session_context: session-order-repair"), true)

    const stable = structuredClone(output.system)
    await hook.event("experimental.chat.system.transform", {
      input: { sessionID: "session-order-repair" },
      output,
      directory,
    })
    assert.deepEqual(output.system, stable)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("stablePromptFingerprint is exact across line endings and boundary whitespace", () => {
  const canonical = stablePromptFingerprint(["system instruction", "second instruction"])
  const formatted = stablePromptFingerprint(["  system instruction\r\n", "\nsecond instruction  "])
  assert.equal(canonical, "0fb4f58ddeab825fb407971be73611fcf8549cd246b7c38acf7dc17d24a486a3")
  assert.notEqual(formatted, canonical)
})

test("stablePromptFingerprint changes for semantic prompt changes", () => {
  const baseline = stablePromptFingerprint(["system instruction", "second instruction"])
  const changed = stablePromptFingerprint(["system instruction", "changed instruction"])
  assert.notEqual(changed, baseline)
})
