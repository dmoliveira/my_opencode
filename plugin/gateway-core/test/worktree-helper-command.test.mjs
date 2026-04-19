import assert from "node:assert/strict"
import { execFileSync } from "node:child_process"
import test from "node:test"
import { fileURLToPath } from "node:url"

const helperPath = fileURLToPath(new URL("../../../scripts/worktree_helper_command.py", import.meta.url))
const repoDirectory = fileURLToPath(new URL("../../../", import.meta.url))

function runHelper(blockedCommand) {
  return JSON.parse(
    execFileSync(
      "python3",
      [
        helperPath,
        "maintenance",
        "--directory",
        repoDirectory,
        "--command",
        blockedCommand,
        "--json",
      ],
      { encoding: "utf-8" },
    ),
  )
}

test("worktree helper tells operators to run allowed oc done directly", () => {
  const report = runHelper('oc done task_175 --note "completed"')

  assert.equal(report.result, "PASS")
  assert.equal(report.mode, "direct_run")
  assert.match(report.note, /already allowed directly on protected main/i)
  assert.deepEqual(report.commands, ['oc done task_175 --note "completed"'])
  assert.ok(!("suggested_worktree" in report))
})

test("worktree helper tells operators to run allowed oc end-session directly", () => {
  const report = runHelper('oc end-session --outcome done session_64 --achievements "cleanup complete"')

  assert.equal(report.result, "PASS")
  assert.equal(report.mode, "direct_run")
  assert.match(report.note, /do not wrap it with the maintenance helper/i)
  assert.deepEqual(report.commands, ['oc end-session --outcome done session_64 --achievements "cleanup complete"'])
})

test("worktree helper still suggests a maintenance worktree for blocked commands", () => {
  const report = runHelper('git commit -m "msg"')

  assert.equal(report.result, "PASS")
  assert.equal(report.mode, "maintenance_worktree")
  assert.match(report.suggested_branch, /^chore\//)
  assert.equal(report.blocked_command, 'git commit -m "msg"')
  assert.equal(report.commands.length, 2)
})

test("worktree helper does not classify chained oc commands as direct-run safe", () => {
  const report = runHelper('oc done task_175 --note "completed" && git commit -m "msg"')

  assert.equal(report.result, "PASS")
  assert.equal(report.mode, "maintenance_worktree")
  assert.equal(report.blocked_command, 'oc done task_175 --note "completed" && git commit -m "msg"')
  assert.equal(report.commands.length, 2)
})
