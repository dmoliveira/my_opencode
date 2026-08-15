import assert from "node:assert/strict"
import test from "node:test"

import { shouldApplyRefresh, shouldBindStateDirectory } from "../dist/sidebar.js"

test("sidebar binds a state watcher when fs.watch omits the changed filename", () => {
  assert.equal(shouldBindStateDirectory(null), true)
  assert.equal(shouldBindStateDirectory(undefined), true)
  assert.equal(shouldBindStateDirectory(".opencode"), true)
  assert.equal(shouldBindStateDirectory(Buffer.from(".opencode")), true)
  assert.equal(shouldBindStateDirectory("other-file"), false)
})

test("sidebar ignores stale or disposed refresh completions", () => {
  assert.equal(shouldApplyRefresh(false, 2, 2), true)
  assert.equal(shouldApplyRefresh(false, 1, 2), false)
  assert.equal(shouldApplyRefresh(true, 2, 2), false)
})
