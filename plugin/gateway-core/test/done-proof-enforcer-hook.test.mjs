import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"
import { createDoneProofEnforcerHook } from "../dist/hooks/done-proof-enforcer/index.js"

test("done-proof-enforcer rewrites DONE promise when validation markers are missing", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-done-proof-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: { enabled: true, order: ["done-proof-enforcer"], disabled: [] },
        doneProofEnforcer: {
          enabled: true,
          requiredMarkers: ["validation", "test", "lint"],
        },
      },
    })
    const output = { output: "all complete\n<promise>DONE</promise>" }
    await plugin["tool.execute.after"]({ tool: "bash", sessionID: "session-proof" }, output)
    assert.ok(output.output.includes("PENDING_VALIDATION"))
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("done-proof-enforcer uses LLM fallback for semantic evidence wording", async () => {
  const hook = createDoneProofEnforcerHook({
    enabled: true,
    requiredMarkers: ["test"],
    requireLedgerEvidence: true,
    allowTextFallback: true,
    directory: process.cwd(),
    decisionRuntime: {
      config: {
        enabled: true,
        mode: "assist",
        command: "opencode",
        model: "openai/gpt-5.1-codex-mini",
        timeoutMs: 1000,
        maxPromptChars: 200,
        maxContextChars: 200,
        enableCache: true,
        cacheTtlMs: 10000,
        maxCacheEntries: 8,
      },
      decide: async () => ({
        mode: "assist",
        accepted: true,
        char: "Y",
        raw: "Y",
        durationMs: 1,
        model: "openai/gpt-5.1-codex-mini",
        templateId: "done-proof-marker-test-v1",
        meaning: "test_present",
      }),
    },
  })

  const output = {
    output: "Completed smoke verification and regression checks successfully.\n<promise>DONE</promise>",
  }
  await hook.event("tool.execute.after", { input: { tool: "bash", sessionID: "session-proof-llm-1" }, output })
  assert.equal(output.output.includes("PENDING_VALIDATION"), false)
})

test("done-proof-enforcer shadow mode records semantic evidence but keeps pending validation", async () => {
  const hook = createDoneProofEnforcerHook({
    enabled: true,
    requiredMarkers: ["test"],
    requireLedgerEvidence: true,
    allowTextFallback: true,
    directory: process.cwd(),
    decisionRuntime: {
      config: {
        enabled: true,
        mode: "shadow",
        command: "opencode",
        model: "openai/gpt-5.1-codex-mini",
        timeoutMs: 1000,
        maxPromptChars: 200,
        maxContextChars: 200,
        enableCache: true,
        cacheTtlMs: 10000,
        maxCacheEntries: 8,
      },
      decide: async () => ({
        mode: "shadow",
        accepted: true,
        char: "Y",
        raw: "Y",
        durationMs: 1,
        model: "openai/gpt-5.1-codex-mini",
        templateId: "done-proof-marker-test-v1",
        meaning: "test_present",
      }),
    },
  })

  const output = {
    output: "Completed smoke verification and regression checks successfully.\n<promise>DONE</promise>",
  }
  await hook.event("tool.execute.after", { input: { tool: "bash", sessionID: "session-proof-shadow-1" }, output })
  assert.equal(output.output.includes("PENDING_VALIDATION"), true)
})

test("done-proof-enforcer rewrites structured bash output payloads", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-done-proof-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: { enabled: true, order: ["done-proof-enforcer"], disabled: [] },
        doneProofEnforcer: { enabled: true, requiredMarkers: ["validation"] },
      },
    })
    const output = { output: { stdout: "all complete\n<promise>DONE</promise>", stderr: "" } }
    await plugin["tool.execute.after"]({ tool: "bash", sessionID: "session-proof-structured" }, output)
    assert.match(String(output.output.stdout), /PENDING_VALIDATION/)
    assert.equal(String(output.output.stderr), "")
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("done-proof-enforcer rewrites stderr-only structured payloads in place", async () => {
  const hook = createDoneProofEnforcerHook({ enabled: true, requiredMarkers: ["validation"] })
  const output = { output: { stdout: "", stderr: "all complete\n<promise>DONE</promise>" } }
  await hook.event("tool.execute.after", { input: { tool: "bash", sessionID: "session-proof-stderr" }, output })
  assert.match(String(output.output.stderr), /PENDING_VALIDATION/)
  assert.equal(String(output.output.stdout), "")
})
