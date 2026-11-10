import assert from "node:assert/strict"
import { mkdtemp, readFile, rm } from "node:fs/promises"
import { tmpdir } from "node:os"
import { resolve } from "node:path"
import test from "node:test"
import plugin from "../dist/index.js"

const root = resolve(import.meta.dirname, "..")

test("compiled sidebar module declares a TUI-only entrypoint", async () => {
  const source = await readFile(resolve(root, "dist/index.js"), "utf8")
  assert.match(source, /sidebar_content/)
  assert.match(source, /SUPPORTED_OPENCODE_VERSION/)
  assert.doesNotMatch(source, /\bmcp\b/i)
  assert.doesNotMatch(source, /chat\.message/)
})

test("verified V1 versions register the sidebar while unknown versions remain disabled", async () => {
  const directory = await mkdtemp(resolve(tmpdir(), "sidebar-version-"))
  try {
    for (const version of ["1.18.18", "1.18.33", "1.18.34"]) {
      const slots = []
      const warnings = []
      let dispose = () => {}
      const api = {
        app: { version },
        ui: { toast: (value) => warnings.push(value) },
        slots: { register: (value) => slots.push(value) },
        state: { path: { directory }, session: { get: () => undefined } },
        renderer: { requestRender() {} },
        event: { on: () => () => {} },
        lifecycle: { onDispose: (value) => { dispose = value } },
      }
      await plugin.tui(api)
      assert.equal(slots.length, version === "1.18.34" ? 0 : 1)
      assert.equal(warnings.length, version === "1.18.34" ? 1 : 0)
      dispose()
    }
  } finally {
    await rm(directory, { recursive: true, force: true })
  }
})
