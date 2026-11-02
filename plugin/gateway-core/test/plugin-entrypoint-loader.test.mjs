import assert from "node:assert/strict"
import test from "node:test"
import { mkdtempSync, realpathSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import * as entrypoint from "../dist/index.js"

// OpenCode 1.18.18 getLegacyPlugins/applyPlugin: enumerate and deduplicate ALL
// namespace values, accepting a function or an object with a server function.
// https://github.com/anomalyco/opencode/blob/v1.18.18/packages/opencode/src/plugin/index.ts
async function initializeNativeLegacyExports(mod, input, options) {
  const seen = new Set()
  const plugins = []
  for (const entry of Object.values(mod)) {
    if (seen.has(entry)) continue
    seen.add(entry)
    const plugin = typeof entry === "function" ? entry
      : entry && typeof entry === "object" && typeof entry.server === "function" ? entry.server : undefined
    if (!plugin) throw new TypeError("Plugin export is not a function")
    plugins.push(plugin)
  }
  const hooks = []
  for (const server of plugins) hooks.push(await server(input, options))
  return hooks
}

test("built gateway namespace initializes through native OpenCode legacy export semantics", async () => {
  const directory = realpathSync(mkdtempSync(join(tmpdir(), "synthetic-entrypoint-loader-")))
  try {
    const loaded = await initializeNativeLegacyExports(entrypoint, { directory }, {})
    assert.equal(loaded.length, 1, "gateway must initialize exactly once without treating internal helpers as plugins")
    const hooks = loaded[0]
    for (const name of ["event", "tool.execute.before", "tool.execute.after", "chat.message", "tool.definition"]) {
      assert.equal(typeof hooks[name], "function", `native initializer must return ${name}`)
    }
    const output = { description: "verbose synthetic description", parameters: {} }
    await hooks["tool.definition"]({ toolID: "read" }, output)
    assert.equal(output.description, "Read a local file or directory by absolute path.")
    assert.equal(Object.hasOwn(entrypoint, "dispatchToolAfterHooks"), false)
  } finally { rmSync(directory, { recursive: true, force: true }) }
})

test("native loader contract invokes distinct named exports and deduplicates aliases", async () => {
  const calls = [], input = {}, options = {}
  const primary = async (i, o) => { assert.equal(i, input); assert.equal(o, options); calls.push("primary"); return {} }
  const secondary = { server: async () => { calls.push("secondary"); return {} } }
  await initializeNativeLegacyExports({ default: primary, alias: primary, named: secondary }, input, options)
  assert.deepEqual(calls, ["primary", "secondary"])
  await assert.rejects(initializeNativeLegacyExports({ default: primary, invalid: {} }, input, options), /Plugin export is not a function/)
})
