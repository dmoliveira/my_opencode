import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"
import { createSessionRuntimeContextHook } from "../dist/hooks/session-runtime-context/index.js"

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

test("session-runtime-context resets injection state after compaction", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-session-runtime-context-"))
  try {
    const hook = createSessionRuntimeContextHook({
      directory,
      enabled: true,
    })
    const output = {
      messages: [
        {
          info: { role: "user", sessionId: "session-runtime-3" },
          parts: [{ type: "text", text: "hello" }],
        },
      ],
    }
    await hook.event("experimental.chat.messages.transform", {
      input: {},
      output,
      directory,
    })
    await hook.event("session.compacted", {
      properties: { info: { id: "session-runtime-3" } },
      directory,
    })
    const resumed = {
      messages: [
        {
          info: { role: "user", sessionId: "session-runtime-3" },
          parts: [{ type: "text", text: "hello again" }],
        },
      ],
    }
    await hook.event("experimental.chat.messages.transform", {
      input: {},
      output: resumed,
      directory,
    })

    assert.match(String(resumed.messages[0]?.parts?.[0]?.text), /authoritative_runtime_session_id=session-runtime-3/)
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
      messages: [
        {
          info: { role: "user", sessionId: "session-runtime-resume" },
          parts: [{ type: "text", text: "First prompt" }],
        },
      ],
    }
    await firstHook.event("experimental.chat.messages.transform", {
      input: {},
      output: firstOutput,
      directory,
    })

    const resumedHook = createSessionRuntimeContextHook({
      directory,
      enabled: true,
    })
    const resumedOutput = {
      messages: [
        {
          info: { role: "user", sessionId: "session-runtime-resume" },
          parts: [{ type: "text", text: "Resumed prompt" }],
        },
      ],
    }
    await resumedHook.event("experimental.chat.messages.transform", {
      input: {},
      output: resumedOutput,
      directory,
    })

    assert.match(String(resumedOutput.messages[0]?.parts?.[0]?.text), /authoritative_runtime_session_id=session-runtime-resume/)
    assert.match(String(resumedOutput.messages[0]?.parts?.[0]?.text), /Resumed prompt/)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("session-runtime-context integrates through default plugin transform hook order", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-session-runtime-context-"))
  try {
    const plugin = GatewayCorePlugin({ directory })
    const output = {
      messages: [
        {
          info: { role: "user", sessionId: "session-runtime-plugin-default" },
          parts: [{ type: "text", text: "Plugin prompt" }],
        },
      ],
    }

    await plugin["experimental.chat.messages.transform"]({ input: {} }, output)

    assert.match(String(output.messages[0]?.parts?.[0]?.text), /\[SESSION CONTEXT\]/)
    assert.match(
      String(output.messages[0]?.parts?.[0]?.text),
      /authoritative_runtime_session_id=session-runtime-plugin-default/,
    )
    assert.match(String(output.messages[0]?.parts?.[0]?.text), /Plugin prompt/)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("session-runtime-context does not mutate visible chat.message output", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-session-runtime-context-"))
  try {
    const plugin = GatewayCorePlugin({ directory })
    const output = {
      parts: [{ type: "text", text: "Visible prompt" }],
    }

    await plugin["chat.message"]({ sessionID: "session-visible-chat" }, output)

    assert.equal(output.parts[0]?.text, "Visible prompt")
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
      messages: [
        {
          info: { role: "user", sessionId: "session-runtime-plugin-disabled" },
          parts: [{ type: "text", text: "No runtime context expected" }],
        },
      ],
    }

    await plugin["experimental.chat.messages.transform"]({ input: {} }, output)

    assert.equal(output.messages[0]?.parts?.[0]?.text, "No runtime context expected")
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
