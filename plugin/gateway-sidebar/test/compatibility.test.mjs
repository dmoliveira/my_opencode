import assert from "node:assert/strict"
import { readFile } from "node:fs/promises"
import { resolve } from "node:path"
import test from "node:test"

const root = resolve(import.meta.dirname, "..")

test("compiled sidebar module declares a TUI-only entrypoint", async () => {
  const source = await readFile(resolve(root, "dist/index.js"), "utf8")
  assert.match(source, /sidebar_content/)
  assert.match(source, /SUPPORTED_OPENCODE_VERSION/)
  assert.doesNotMatch(source, /\bmcp\b/i)
  assert.doesNotMatch(source, /chat\.message/)
})
