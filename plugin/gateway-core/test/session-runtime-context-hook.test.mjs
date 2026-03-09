import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"
import { createSessionRuntimeContextHook } from "../dist/hooks/session-runtime-context/index.js"

test("session-runtime-context injects authoritative session id into first chat message", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-session-runtime-context-"))
  try {
    const hook = createSessionRuntimeContextHook({
      directory,
      enabled: true,
    })
    const output = {
      parts: [{ type: "text", text: "Original prompt" }],
    }
    await hook.event("chat.message", {
      properties: { sessionID: "session-runtime-1" },
      output,
      directory,
    })

    assert.match(String(output.parts[0]?.text), /\[SESSION CONTEXT\]/)
    assert.match(String(output.parts[0]?.text), /authoritative_runtime_session_id=session-runtime-1/)
    assert.match(String(output.parts[0]?.text), /Original prompt/)

    await hook.event("chat.message", {
      properties: { sessionID: "session-runtime-1" },
      output,
      directory,
    })
    assert.equal(String(output.parts[0]?.text).match(/\[SESSION CONTEXT\]/g)?.length ?? 0, 1)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("session-runtime-context injects authoritative session id into transform payloads", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-session-runtime-context-"))
  try {
    const hook = createSessionRuntimeContextHook({
      directory,
      enabled: true,
    })
    const output = {
      messages: [
        { info: { role: "assistant" }, parts: [{ type: "text", text: "A" }] },
        {
          info: { role: "user", sessionId: "session-runtime-2" },
          parts: [{ type: "text", text: "B" }],
        },
      ],
    }
    await hook.event("experimental.chat.messages.transform", {
      input: {},
      output,
      directory,
    })

    assert.match(String(output.messages[1]?.parts?.[0]?.text), /authoritative_runtime_session_id=session-runtime-2/)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("session-runtime-context restores authoritative session id after compaction", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-session-runtime-context-"))
  try {
    let promptCalls = 0
    const hook = createSessionRuntimeContextHook({
      directory,
      enabled: true,
      client: {
        session: {
          async promptAsync() {
            promptCalls += 1
          },
          async messages() {
            return { data: [] }
          },
        },
      },
    })

    await hook.event("chat.message", {
      properties: { sessionID: "session-runtime-3" },
      output: { parts: [{ type: "text", text: "hello" }] },
      directory,
    })
    await hook.event("session.compacted", {
      properties: { info: { id: "session-runtime-3" } },
      directory,
    })

    assert.equal(promptCalls, 1)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})


test("session-runtime-context reinjects on resumed session with fresh hook instance", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-session-runtime-context-"))
  try {
    const firstHook = createSessionRuntimeContextHook({
      directory,
      enabled: true,
    })
    const firstOutput = {
      parts: [{ type: "text", text: "First prompt" }],
    }
    await firstHook.event("chat.message", {
      properties: { sessionID: "session-runtime-resume" },
      output: firstOutput,
      directory,
    })

    const resumedHook = createSessionRuntimeContextHook({
      directory,
      enabled: true,
    })
    const resumedOutput = {
      parts: [{ type: "text", text: "Resumed prompt" }],
    }
    await resumedHook.event("chat.message", {
      properties: { sessionID: "session-runtime-resume" },
      output: resumedOutput,
      directory,
    })

    assert.match(String(resumedOutput.parts[0]?.text), /authoritative_runtime_session_id=session-runtime-resume/)
    assert.match(String(resumedOutput.parts[0]?.text), /Resumed prompt/)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})


test("session-runtime-context integrates through default plugin hook order", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-session-runtime-context-"))
  try {
    const plugin = GatewayCorePlugin({ directory })
    const output = {
      parts: [{ type: "text", text: "Plugin prompt" }],
    }

    await plugin["chat.message"](
      {
        sessionID: "session-runtime-plugin-default",
      },
      output,
    )

    assert.match(String(output.parts[0]?.text), /\[SESSION CONTEXT\]/)
    assert.match(
      String(output.parts[0]?.text),
      /authoritative_runtime_session_id=session-runtime-plugin-default/,
    )
    assert.match(String(output.parts[0]?.text), /Plugin prompt/)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("session-runtime-context can be disabled through plugin config", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-session-runtime-context-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        sessionRuntimeContextInjector: {
          enabled: false,
        },
      },
    })
    const output = {
      parts: [{ type: "text", text: "No runtime context expected" }],
    }

    await plugin["chat.message"](
      {
        sessionID: "session-runtime-plugin-disabled",
      },
      output,
    )

    assert.equal(output.parts[0]?.text, "No runtime context expected")
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
