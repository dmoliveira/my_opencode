import assert from "node:assert/strict"
import { spawnSync } from "node:child_process"
import test from "node:test"

import { createLlmDecisionRuntime } from "../dist/hooks/shared/llm-decision-runtime.js"

const sessionID = "ses_fixture"
const messageID = "msg_fixture"
const start = { type: "step_start", sessionID, part: { type: "step-start", sessionID, messageID } }
const text = { type: "text", sessionID, part: { type: "text", sessionID, messageID, text: "Y" } }
const finish = { type: "step_finish", sessionID, part: { type: "step-finish", sessionID, messageID, reason: "stop" } }
const line = (value) => JSON.stringify(value)
const trace = (...values) => values.map(line).join("\n") + "\n"
const valid = trace(start, text, finish)

function runtimeFor(runner, enableCache = false) {
  return createLlmDecisionRuntime({
    directory: "/nonexistent",
    config: {
      enabled: true, mode: "assist", hookModes: {}, command: "fixture", model: "fixture/model",
      env: {}, allowStandaloneOpencode: false, timeoutMs: 1000, failureCooldownMs: 1000,
      maxConcurrentDecisions: 1, maxPromptChars: 200, maxContextChars: 200,
      enableCache, cacheTtlMs: 10000, maxCacheEntries: 4,
    },
    runner,
  })
}

const request = {
  hookId: "fixture", sessionId: "parent_fixture", templateId: "fixture",
  instruction: "Choose", context: "synthetic", allowedChars: ["Y", "N"],
  cacheKey: "synthetic-cache-key",
}

test("accepts a complete, tool-free decision trace", async () => {
  const runtime = runtimeFor(async () => ({ stdout: valid, stderr: "" }))
  const result = await runtime.decide(request)
  assert.equal(result.accepted, true)
  assert.equal(result.char, "Y")
})

test("rejects incomplete, malformed, errored or ambiguous event evidence", async (t) => {
  const tool = (name) => ({
    type: "tool_use", sessionID,
    part: { type: "tool", sessionID, messageID, tool: name, state: { input: { command: "git push" } } },
  })
  const cases = {
    empty: "",
    text_only: trace(text),
    truncated: trace(start, text),
    missing_start: trace(text, finish),
    malformed_leading: `not-json\n${valid}`,
    malformed_trailing: `${valid}{"type":\n`,
    array: `${valid}[]\n`,
    null_event: `${valid}null\n`,
    error: `${valid}${line({ type: "error", sessionID, error: { message: "synthetic" } })}\n`,
    error_during_step: trace(start, { type: "error", sessionID, error: { message: "synthetic" } }, text, finish),
    event_error: trace(start, text, { ...finish, error: { message: "synthetic" } }),
    part_error: trace(start, text, { ...finish, part: { ...finish.part, error: { message: "synthetic" } } }),
    unknown: trace(start, { type: "mystery", sessionID, part: {} }, text, finish),
    v1_bash: trace(start, tool("bash"), text, finish),
    v2_shell: trace(start, tool("shell"), text, finish),
    read_tool: trace(start, tool("read"), text, finish),
    prior_tool_step: trace(start, tool("shell"), { ...finish, part: { ...finish.part, reason: "tool-calls" } }, start, text, finish),
    other_session: trace(start, { ...text, sessionID: "ses_other" }, finish),
    other_part_session: trace(start, { ...text, part: { ...text.part, sessionID: "ses_other" } }, finish),
    other_message: trace(start, { ...text, part: { ...text.part, messageID: "msg_other" } }, finish),
    no_message: trace(start, { ...text, part: { type: "text", sessionID, text: "Y" } }, finish),
    blank_session: trace(...[start, text, finish].map((event) => ({
      ...event, sessionID: " ", part: { ...event.part, sessionID: " " },
    }))),
    blank_message: trace(...[start, text, finish].map((event) => ({
      ...event, part: { ...event.part, messageID: " " },
    }))),
    synthetic_text: trace(start, { ...text, part: { ...text.part, synthetic: true } }, finish),
    ignored_text: trace(start, { ...text, part: { ...text.part, ignored: true } }, finish),
    malformed_synthetic: trace(start, { ...text, part: { ...text.part, synthetic: "false" } }, finish),
    malformed_ignored: trace(start, { ...text, part: { ...text.part, ignored: null } }, finish),
    wrong_part_type: trace(start, { ...text, part: { ...text.part, type: "tool" } }, finish),
    duplicate_text: trace(start, text, { ...text, part: { ...text.part, text: "" } }, finish),
    nonterminal_finish: trace(start, text, { ...finish, part: { ...finish.part, reason: "tool-calls" } }),
    length_finish: trace(start, text, { ...finish, part: { ...finish.part, reason: "length" } }),
    trailing_event: `${valid}${line(text)}\n`,
    duplicate_type: `{"type":"error","type":"step_start","sessionID":"${sessionID}","part":{"type":"step-start","sessionID":"${sessionID}","messageID":"${messageID}"}}\n${trace(text, finish)}`,
    escaped_duplicate_type: `{"type":"error","\\u0074ype":"step_start","sessionID":"${sessionID}","part":{"type":"step-start","sessionID":"${sessionID}","messageID":"${messageID}"}}\n${trace(text, finish)}`,
    escaped_duplicate_text: `${line(start)}\n{"type":"text","sessionID":"${sessionID}","part":{"type":"text","sessionID":"${sessionID}","messageID":"${messageID}","text":"N","te\\u0078t":"Y"}}\n${line(finish)}\n`,
    duplicate_nested_metadata: trace(start, { ...text, extra: { ignored: 1 } }, finish).replace('"ignored":1', '"ignored":1,"ignored":2'),
    oversized: trace(start, { ...text, extra: "x".repeat(70000) }, finish),
  }
  for (const [name, stdout] of Object.entries(cases)) {
    await t.test(name, async () => {
      const result = await runtimeFor(async () => ({ stdout, stderr: "" })).decide(request)
      assert.equal(result.accepted, false)
      assert.equal(result.skippedReason, "invalid_response")
    })
  }
})

test("accepts valid whitespace and nested string syntax without confusing keys", async () => {
  const withMetadata = {
    ...text,
    part: { ...text.part, synthetic: false, ignored: false },
    extra: { nested: [{ "a:b": "comma, quote\" and brace}" }, { "a:b": "same key in a different object" }] },
  }
  const stdout = [start, withMetadata, finish].map((item) => `  ${line(item)}  `).join("\n") + "\n"
  const result = await runtimeFor(async () => ({ stdout, stderr: "" })).decide(request)
  assert.equal(result.accepted, true)
  assert.equal(result.char, "Y")
})

test("an invalid trace is not accepted or cached before a valid retry", async () => {
  let calls = 0
  const runtime = runtimeFor(async () => ({
    stdout: ++calls === 1 ? `${valid}{broken\n` : valid,
    stderr: "",
  }), true)
  const invalid = await runtime.decide(request)
  const accepted = await runtime.decide(request)
  const cached = await runtime.decide(request)
  assert.equal(invalid.accepted, false)
  assert.equal(invalid.skippedReason, "invalid_response")
  assert.equal(accepted.accepted, true)
  assert.equal(cached.accepted, true)
  assert.equal(cached.cached, true)
  assert.equal(calls, 2)
})

test("inherited fields cannot replace missing JSON evidence", () => {
  const moduleUrl = new URL("../dist/hooks/shared/llm-decision-runtime.js", import.meta.url).href
  const program = `
    import assert from "node:assert/strict"
    import { createLlmDecisionRuntime } from ${JSON.stringify(moduleUrl)}
    const id = "ses_fixture", message = "msg_fixture"
    const config = {enabled:true,mode:"assist",hookModes:{},command:"fixture",model:"fixture/model",env:{},timeoutMs:1000,failureCooldownMs:1000,maxConcurrentDecisions:1,maxPromptChars:200,maxContextChars:200,enableCache:false,cacheTtlMs:1000,maxCacheEntries:1}
    const request = {hookId:"fixture",sessionId:"parent",templateId:"fixture",instruction:"choose",context:"synthetic",allowedChars:["Y","N"]}
    const cases = [
      ["event type", "type", "step_start", (s) => delete s.start.type],
      ["event part", "part", {type:"step-start",sessionID:id,messageID:message}, (s) => delete s.start.part],
      ["event session", "sessionID", id, (s) => delete s.start.sessionID],
      ["part type", "type", "step-start", (s) => delete s.start.part.type],
      ["part session", "sessionID", id, (s) => delete s.start.part.sessionID],
      ["part message", "messageID", message, (s) => delete s.start.part.messageID],
      ["text", "text", "Y", (s) => delete s.text.part.text],
      ["reason", "reason", "stop", (s) => delete s.finish.part.reason],
    ]
    for (const [label, key, value, omit] of cases) {
      const parts = {
        start:{type:"step_start",sessionID:id,part:{type:"step-start",sessionID:id,messageID:message}},
        text:{type:"text",sessionID:id,part:{type:"text",sessionID:id,messageID:message,text:"Y"}},
        finish:{type:"step_finish",sessionID:id,part:{type:"step-finish",sessionID:id,messageID:message,reason:"stop"}},
      }
      omit(parts)
      const stdout = [parts.start,parts.text,parts.finish].map(JSON.stringify).join("\\n") + "\\n"
      assert.equal(Object.hasOwn(Object.prototype,key), false)
      Object.defineProperty(Object.prototype,key,{value,configurable:true})
      try {
        const runtime = createLlmDecisionRuntime({directory:"/nonexistent",config,runner:async()=>({stdout,stderr:""})})
        const result = await runtime.decide(request)
        assert.equal(result.accepted, false, label)
        assert.equal(result.skippedReason, "invalid_response", label)
      } finally {
        delete Object.prototype[key]
      }
    }
    for (const key of ["synthetic", "ignored"]) {
      const parts = [
        {type:"step_start",sessionID:id,part:{type:"step-start",sessionID:id,messageID:message}},
        {type:"text",sessionID:id,part:{type:"text",sessionID:id,messageID:message,text:"Y"}},
        {type:"step_finish",sessionID:id,part:{type:"step-finish",sessionID:id,messageID:message,reason:"stop"}},
      ]
      const stdout = parts.map(JSON.stringify).join("\\n") + "\\n"
      Object.defineProperty(Object.prototype,key,{value:true,configurable:true})
      try {
        const runtime = createLlmDecisionRuntime({directory:"/nonexistent",config,runner:async()=>({stdout,stderr:""})})
        const result = await runtime.decide(request)
        assert.equal(result.accepted, true, key)
      } finally {
        delete Object.prototype[key]
      }
    }
  `
  const child = spawnSync(process.execPath, ["--input-type=module", "-e", program], {
    cwd: process.cwd(), env: { HOME: "/nonexistent", PATH: process.env.PATH ?? "", LANG: "C" },
    encoding: "utf8", timeout: 10000,
  })
  assert.equal(child.status, 0, child.stderr || String(child.error))
})
