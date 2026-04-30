import assert from "node:assert/strict"
import { execFileSync } from "node:child_process"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
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

function runHelperWithArgs(args, options = {}) {
  try {
    return {
      status: 0,
      stdout: execFileSync("python3", [helperPath, ...args], {
        encoding: "utf-8",
        cwd: options.cwd,
      }),
    }
  } catch (error) {
    return {
      status: error.status ?? 1,
      stdout: error.stdout,
      stderr: error.stderr,
    }
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
  const npmInstallReport = runHelper("npm install --yes")
  const npmCiReport = runHelper("npm ci --yes --no-audit --no-fund")
  const npmInitReport = runHelper("npm init -y")
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
  assert.equal(npmInstallReport.result, "PASS")
  assert.equal(npmInstallReport.mode, "direct_run")
  assert.equal(npmCiReport.result, "PASS")
  assert.equal(npmCiReport.mode, "direct_run")
  assert.equal(npmInitReport.result, "PASS")
  assert.equal(npmInitReport.mode, "direct_run")
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

test("worktree helper stays aligned with newly allowed read-only git inspection commands", () => {
  const mergeBaseReport = runHelper("git merge-base HEAD main")
  const revListReport = runHelper("git rev-list --count main..HEAD")
  const showReport = runHelper("git show --stat HEAD")
  const symbolicRefReport = runHelper("git symbolic-ref --short HEAD")
  const branchListReport = runHelper("git branch --list feature/*")
  const worktreeListReport = runHelper("git worktree list --porcelain")

  assert.equal(mergeBaseReport.result, "PASS")
  assert.equal(mergeBaseReport.mode, "direct_run")
  assert.equal(revListReport.result, "PASS")
  assert.equal(revListReport.mode, "direct_run")
  assert.equal(showReport.result, "PASS")
  assert.equal(showReport.mode, "direct_run")
  assert.equal(symbolicRefReport.result, "PASS")
  assert.equal(symbolicRefReport.mode, "direct_run")
  assert.equal(branchListReport.result, "PASS")
  assert.equal(branchListReport.mode, "direct_run")
  assert.equal(worktreeListReport.result, "PASS")
  assert.equal(worktreeListReport.mode, "direct_run")
})

test("worktree helper keeps path-switching npm bootstrap commands blocked", () => {
  const report = runHelper("npm install --yes --prefix /tmp/other-project")

  assert.equal(report.result, "FAIL")
  assert.equal(report.mode, "maintenance_worktree")
  assert.equal(report.blocked_command, "npm install --yes --prefix /tmp/other-project")
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

test("worktree helper execute mode runs the blocked command in place", () => {
  const report = JSON.parse(
    runHelperWithArgs([
      "maintenance",
      "--directory",
      repoDirectory,
      "--command",
      'python3 -c "print(123)"',
      "--execute",
      "--json",
    ]).stdout,
  )

  assert.equal(report.result, "EXECUTED")
  assert.equal(report.returncode, 0)
  assert.equal(report.stdout.trim(), "123")
  assert.equal(report.stderr, "")
})

test("worktree helper execute mode supports env-prefixed commands without a shell", () => {
  const report = JSON.parse(
    runHelperWithArgs([
      "maintenance",
      "--directory",
      repoDirectory,
      "--command",
      'env DEMO_VALUE=456 python3 -c "import os; print(os.environ[\'DEMO_VALUE\'])"',
      "--execute",
      "--json",
    ]).stdout,
  )

  assert.equal(report.result, "EXECUTED")
  assert.equal(report.returncode, 0)
  assert.equal(report.stdout.trim(), "456")
})

test("worktree helper execute mode supports bare env assignment prefixes", () => {
  const report = JSON.parse(
    runHelperWithArgs([
      "maintenance",
      "--directory",
      repoDirectory,
      "--command",
      'DEMO_VALUE=789 python3 -c "import os; print(os.environ[\'DEMO_VALUE\'])"',
      "--execute",
      "--json",
    ]).stdout,
  )

  assert.equal(report.result, "EXECUTED")
  assert.equal(report.returncode, 0)
  assert.equal(report.stdout.trim(), "789")
})

test("worktree helper execute mode rejects chained shell syntax", () => {
  const report = JSON.parse(
    runHelperWithArgs([
      "maintenance",
      "--directory",
      repoDirectory,
      "--command",
      'python3 -c "print(1)" && python3 -c "print(2)"',
      "--execute",
      "--json",
    ]).stdout,
  )

  assert.equal(report.result, "ERROR")
  assert.match(report.error, /single command without shell chaining or redirection/)
})

test("worktree helper execute mode rejects redirection and pipeline syntax", () => {
  const redirectReport = JSON.parse(
    runHelperWithArgs([
      "maintenance",
      "--directory",
      repoDirectory,
      "--command",
      'python3 -c "print(1)" > /tmp/worktree-helper-test',
      "--execute",
      "--json",
    ]).stdout,
  )
  const pipelineReport = JSON.parse(
    runHelperWithArgs([
      "maintenance",
      "--directory",
      repoDirectory,
      "--command",
      'python3 -c "print(1)" | python3 -c "print(2)"',
      "--execute",
      "--json",
    ]).stdout,
  )

  assert.equal(redirectReport.result, "ERROR")
  assert.match(redirectReport.error, /single command without shell chaining or redirection/)
  assert.equal(pipelineReport.result, "ERROR")
  assert.match(pipelineReport.error, /single command without shell chaining or redirection/)
})

test("worktree helper falls back to initial-commit guidance when HEAD is missing", () => {
  const tempRoot = mkdtempSync(join(tmpdir(), "worktree-helper-no-head-"))
  try {
    execFileSync("git", ["init", "-b", "main", tempRoot], { encoding: "utf-8" })
    const report = JSON.parse(
      runHelperWithArgs([
        "maintenance",
        "--directory",
        tempRoot,
        "--command",
        'git commit -m "msg"',
        "--json",
      ]).stdout,
    )

    assert.equal(report.result, "FAIL")
    assert.equal(report.mode, "maintenance_worktree")
    assert.match(report.commands[0], /git -C .* add \. && git -C .* commit -m "Initial commit"/)
    assert.match(report.commands[1], /status --short --branch$/)
  } finally {
    rmSync(tempRoot, { recursive: true, force: true })
  }
})
