import assert from "node:assert/strict"
import test from "node:test"

import { isAllowedProtectedShellCommand } from "../dist/hooks/protected-shell-policy.js"

test("protected shell policy allows chained oc status bundles", () => {
  assert.equal(
    isAllowedProtectedShellCommand("oc current || true; printf '\n---\n'; oc next || true; printf '\n---\n'; oc queue || true"),
    true,
  )
})

test("protected shell policy allows codememory task/session creation on protected main", () => {
  assert.equal(
    isAllowedProtectedShellCommand('oc add task "Improve gateway stall recovery" --scope dmoliveira/my_opencode --kind feature --priority P1'),
    true,
  )
  assert.equal(
    isAllowedProtectedShellCommand('oc add session "Implement gateway stall recovery fixes" --task task_112 --worktree . --branch feat/gateway-stall-recovery'),
    true,
  )
})

test("protected shell policy allows readonly sqlite CTE selects", () => {
  assert.equal(
    isAllowedProtectedShellCommand('sqlite3 -readonly "/tmp/runtime.db" "WITH hits AS (SELECT 1 AS id) SELECT id FROM hits;"'),
    true,
  )
})

test("protected shell policy allows fetch with remote target", () => {
  assert.equal(isAllowedProtectedShellCommand("git fetch --prune origin"), true)
})

test("protected shell policy keeps mutating sqlite pragmas blocked", () => {
  assert.equal(
    isAllowedProtectedShellCommand('sqlite3 -readonly "/tmp/runtime.db" "PRAGMA journal_mode=WAL;"'),
    false,
  )
})

test("protected shell policy keeps multiline sqlite statements blocked", () => {
  assert.equal(
    isAllowedProtectedShellCommand(`sqlite3 -readonly "/tmp/runtime.db" "SELECT 1
.shell touch /tmp/pwn"`),
    false,
  )
})

test("protected shell policy keeps unsafe oc bundle syntax blocked", () => {
  assert.equal(isAllowedProtectedShellCommand("oc current > /tmp/out || true"), false)
})

test("protected shell policy keeps option-like fetch targets blocked", () => {
  assert.equal(isAllowedProtectedShellCommand("git fetch --upload-pack=/tmp/evil origin"), false)
})
