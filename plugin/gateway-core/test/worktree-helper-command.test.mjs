import assert from "node:assert/strict"
import { execFileSync } from "node:child_process"
import test from "node:test"
import { fileURLToPath } from "node:url"

const helperPath = fileURLToPath(new URL("../../../scripts/worktree_helper_command.py", import.meta.url))
const repoDirectory = fileURLToPath(new URL("../../../", import.meta.url))

function runHelper(blockedCommand) {
  try {
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
  } catch (error) {
    return JSON.parse(error.stdout)
  }
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

test("worktree helper does not classify bare oc closeout verbs as direct-run safe", () => {
  const doneReport = runHelper("oc done")
  const sessionReport = runHelper("oc end-session")

  assert.equal(doneReport.mode, "maintenance_worktree")
  assert.equal(doneReport.result, "FAIL")
  assert.equal(sessionReport.mode, "maintenance_worktree")
  assert.equal(sessionReport.result, "FAIL")
})

test("worktree helper treats scoped oc status commands as direct-run safe guidance", () => {
  const report = runHelper("oc next --scope dmoliveira/my_opencode --limit 5")

  assert.equal(report.result, "PASS")
  assert.equal(report.mode, "direct_run")
  assert.deepEqual(report.commands, ["oc next --scope dmoliveira/my_opencode --limit 5"])
})

test("worktree helper treats protected-main bootstrap commands as direct-run safe guidance", () => {
  const fetchReport = runHelper("git fetch --all --prune --quiet")
  const pullReport = runHelper("git pull --rebase --autostash")
  const remoteGetUrlReport = runHelper("git remote get-url origin")
  const stashListReport = runHelper("git stash list")
  const ghReport = runHelper("gh auth status")
  const ghPrViewReport = runHelper("gh pr view --json number")
  const ghRepoEditReport = runHelper("gh repo edit --visibility private")
  const dateReport = runHelper('date +"%Y-%m-%d %H:%M"')
  const envBypassReport = runHelper("BASH_ENV=/tmp/evil.sh gh auth status")

  assert.equal(fetchReport.result, "PASS")
  assert.equal(fetchReport.mode, "direct_run")
  assert.equal(pullReport.result, "PASS")
  assert.equal(pullReport.mode, "direct_run")
  assert.equal(remoteGetUrlReport.result, "PASS")
  assert.equal(remoteGetUrlReport.mode, "direct_run")
  assert.equal(stashListReport.result, "PASS")
  assert.equal(stashListReport.mode, "direct_run")
  assert.equal(ghReport.result, "PASS")
  assert.equal(ghReport.mode, "direct_run")
  assert.equal(ghPrViewReport.result, "PASS")
  assert.equal(ghPrViewReport.mode, "direct_run")
  assert.equal(ghRepoEditReport.result, "PASS")
  assert.equal(ghRepoEditReport.mode, "direct_run")
  assert.equal(dateReport.result, "PASS")
  assert.equal(dateReport.mode, "direct_run")
  assert.equal(envBypassReport.result, "FAIL")
  assert.equal(envBypassReport.mode, "maintenance_worktree")
})

test("worktree helper still suggests a maintenance worktree for blocked commands", () => {
  const report = runHelper('git commit -m "msg"')

  assert.equal(report.result, "FAIL")
  assert.equal(report.mode, "maintenance_worktree")
  assert.match(report.suggested_branch, /^chore\//)
  assert.match(report.suggested_worktree, /-wt-maintenance$/)
  assert.match(report.commands[0], /-wt-maintenance HEAD$/)
  assert.match(report.note, /blocked command was not executed/i)
  assert.equal(report.blocked_command, 'git commit -m "msg"')
  assert.equal(report.commands.length, 2)
})

test("worktree helper does not classify chained oc commands as direct-run safe", () => {
  const report = runHelper('oc done task_175 --note "completed" && git commit -m "msg"')

  assert.equal(report.result, "FAIL")
  assert.equal(report.mode, "maintenance_worktree")
  assert.match(report.note, /blocked command was not executed/i)
  assert.equal(report.blocked_command, 'oc done task_175 --note "completed" && git commit -m "msg"')
  assert.equal(report.commands.length, 2)
})
