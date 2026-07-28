import assert from "node:assert/strict"
import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import { gatewayEventAuditPath } from "../dist/audit/event-audit.js"
import {
  cacheableSystemPrefixObservation,
  resolvePromptCacheScopeIdentity,
  stablePromptCacheKey,
} from "../dist/cache/prompt-cache.js"
import GatewayCorePlugin from "../dist/index.js"

function chatParamsInput(sessionID, providerID = "openai") {
  return {
    sessionID,
    agent: "build",
    model: { providerID, modelID: "gpt-5.6-sol" },
    provider: { id: providerID },
    message: {},
  }
}

function chatParamsOutput(promptCacheKey) {
  return {
    temperature: 0.2,
    topP: 1,
    topK: 0,
    maxOutputTokens: 4096,
    options: { promptCacheKey },
  }
}

test("prompt cache scope resolves linked worktrees to one git common directory", () => {
  const root = mkdtempSync(join(tmpdir(), "gateway-prompt-cache-scope-"))
  try {
    const main = join(root, "main")
    const linked = join(root, "linked")
    const gitDirectory = join(main, ".git")
    const linkedGitDirectory = join(gitDirectory, "worktrees", "linked")
    mkdirSync(linkedGitDirectory, { recursive: true })
    mkdirSync(join(linked, "nested"), { recursive: true })
    writeFileSync(join(linked, ".git"), `gitdir: ${linkedGitDirectory}\n`, "utf8")
    writeFileSync(join(linkedGitDirectory, "commondir"), "../..\n", "utf8")

    assert.equal(resolvePromptCacheScopeIdentity(main), resolvePromptCacheScopeIdentity(linked))
    assert.equal(
      resolvePromptCacheScopeIdentity(join(root, "outside", "missing")),
      join(root, "outside", "missing"),
    )
  } finally {
    rmSync(root, { recursive: true, force: true })
  }
})

test("stable prompt cache keys share one scope without exposing raw identity", () => {
  const base = {
    scopeIdentity: "/private/repository/.git",
    providerID: "openai",
    modelID: "gpt-5.6-sol",
    agent: "Build",
    shardCount: 1,
  }
  const first = stablePromptCacheKey({ ...base, sessionID: "session-one" })
  const second = stablePromptCacheKey({ ...base, sessionID: "session-two" })
  assert.ok(first)
  assert.ok(second)
  assert.equal(first.key, second.key)
  assert.match(first.key, /^ocpc-v1:[a-f0-9]{24}:n1:s0$/)
  assert.equal(first.key.length < 48, true)
  assert.equal(first.key.includes("private"), false)
  assert.equal(first.key.includes("gpt-5.6-sol"), false)
  assert.equal(first.key.includes("build"), false)

  const differentModel = stablePromptCacheKey({
    ...base,
    modelID: "gpt-5.4",
    sessionID: "session-one",
  })
  assert.notEqual(differentModel?.key, first.key)

  const sharded = stablePromptCacheKey({
    ...base,
    sessionID: "session-one",
    shardCount: 16,
  })
  assert.ok(sharded)
  assert.equal(sharded.shard >= 0 && sharded.shard < 16, true)
  assert.equal(
    stablePromptCacheKey({ ...base, sessionID: "session-one", shardCount: 16 })?.key,
    sharded.key,
  )
  assert.equal(stablePromptCacheKey({ ...base, sessionID: "", shardCount: 1 }), null)
  assert.equal(stablePromptCacheKey({ ...base, sessionID: "x", shardCount: 0 }), null)
})

test("cacheable system prefix fingerprint is exact and handles a missing marker", () => {
  const withMarker = cacheableSystemPrefixObservation([
    "stable",
    "runtime_concise_mode: lite\nconcise rules",
    "runtime_session_context: session-one",
    "volatile suffix",
  ])
  assert.equal(withMarker.entryCount, 2)
  assert.equal(
    withMarker.charCount,
    "stable".length + "runtime_concise_mode: lite\nconcise rules".length,
  )
  assert.equal(withMarker.sessionMarkerPresent, true)

  const missingMarker = cacheableSystemPrefixObservation([
    "stable",
    "unmanaged\nmentions runtime_session_context: as prose",
  ])
  assert.equal(missingMarker.entryCount, 2)
  assert.equal(missingMarker.sessionMarkerPresent, false)
  assert.notEqual(missingMarker.sha256, withMarker.sha256)
  assert.notEqual(
    cacheableSystemPrefixObservation(["stable\r\n"]).sha256,
    cacheableSystemPrefixObservation(["stable\n"]).sha256,
  )
})

test("chat.params replaces only the upstream OpenAI session cache key", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-prompt-cache-routing-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: { enabled: false, order: [], disabled: [] },
        promptCache: { stableKeyEnabled: true, shardCount: 1 },
      },
    })
    const first = chatParamsOutput("session-one")
    const second = chatParamsOutput("session-two")
    await plugin["chat.params"](chatParamsInput("session-one"), first)
    await plugin["chat.params"](chatParamsInput("session-two"), second)
    assert.match(first.options.promptCacheKey, /^ocpc-v1:[a-f0-9]{24}:n1:s0$/)
    assert.equal(second.options.promptCacheKey, first.options.promptCacheKey)

    const custom = chatParamsOutput("operator-custom-key")
    await plugin["chat.params"](chatParamsInput("session-three"), custom)
    assert.equal(custom.options.promptCacheKey, "operator-custom-key")

    const absent = chatParamsOutput(undefined)
    delete absent.options.promptCacheKey
    await plugin["chat.params"](chatParamsInput("session-four"), absent)
    assert.equal("promptCacheKey" in absent.options, false)

    for (const nonString of [null, 42, { source: "operator" }]) {
      const preserved = chatParamsOutput(nonString)
      await plugin["chat.params"](chatParamsInput("session-non-string"), preserved)
      assert.deepEqual(preserved.options.promptCacheKey, nonString)
    }

    const providerAbsent = chatParamsOutput("session-provider-absent")
    const providerAbsentInput = chatParamsInput("session-provider-absent")
    providerAbsentInput.provider = {}
    await plugin["chat.params"](providerAbsentInput, providerAbsent)
    assert.match(providerAbsent.options.promptCacheKey, /^ocpc-v1:[a-f0-9]{24}:n1:s0$/)

    const otherProvider = chatParamsOutput("session-five")
    await plugin["chat.params"](chatParamsInput("session-five", "anthropic"), otherProvider)
    assert.equal(otherProvider.options.promptCacheKey, "session-five")

    const conflictingProvider = chatParamsOutput("session-six")
    const conflictingInput = chatParamsInput("session-six")
    conflictingInput.provider.id = "azure"
    await plugin["chat.params"](conflictingInput, conflictingProvider)
    assert.equal(conflictingProvider.options.promptCacheKey, "session-six")
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("prompt cache routing can be disabled and audits no key or scope identity", { concurrency: false }, async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-prompt-cache-audit-"))
  const previousAudit = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
  process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = "1"
  try {
    const disabled = GatewayCorePlugin({
      directory,
      config: {
        hooks: { enabled: false, order: [], disabled: [] },
        promptCache: { stableKeyEnabled: false, shardCount: 1 },
      },
    })
    const unchanged = chatParamsOutput("session-disabled")
    await disabled["chat.params"](chatParamsInput("session-disabled"), unchanged)
    assert.equal(unchanged.options.promptCacheKey, "session-disabled")

    const enabled = GatewayCorePlugin({
      directory,
      config: {
        hooks: { enabled: true, order: ["session-runtime-system-context"], disabled: [] },
        promptCache: { stableKeyEnabled: true, shardCount: 1 },
      },
    })
    const system = { system: ["stable system"] }
    await enabled["experimental.chat.system.transform"](
      { sessionID: "session-audit", model: { providerID: "openai", modelID: "gpt-5.6-sol" } },
      system,
    )
    const routed = chatParamsOutput("session-audit")
    await enabled["chat.params"](chatParamsInput("session-audit"), routed)

    const rows = readFileSync(gatewayEventAuditPath(directory), "utf8")
      .trim()
      .split("\n")
      .map((line) => JSON.parse(line))
    const auditText = JSON.stringify(rows)
    const routing = rows.find(
      (row) =>
        row.reason_code === "agent_runtime_model_observed" &&
        row.prompt_cache_strategy === "stable_sharded",
    )
    assert.equal(routing?.prompt_cache_strategy, "stable_sharded")
    assert.equal(routing?.prompt_cache_shard_count, 1)
    assert.equal(routing?.prompt_cache_shard, 0)
    for (const forbidden of [
      "prompt_cache_key",
      "promptCacheKey",
      "prompt_cache_scope",
      "prompt_cache_scope_digest",
      "directory",
      "path",
    ]) {
      assert.equal(forbidden in routing, false)
    }
    const prefix = rows.find((row) => row.reason_code === "prompt_cache_prefix_observed")
    assert.match(prefix?.cacheable_system_prefix_sha256 ?? "", /^[a-f0-9]{64}$/)
    assert.equal(prefix?.cacheable_system_prefix_entry_count, 1)
    assert.equal(prefix?.runtime_session_marker_present, true)
    assert.equal(auditText.includes(routed.options.promptCacheKey), false)
    assert.equal(auditText.includes(resolvePromptCacheScopeIdentity(directory)), false)
  } finally {
    if (previousAudit === undefined) delete process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
    else process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = previousAudit
    rmSync(directory, { recursive: true, force: true })
  }
})
