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
        env: { ...process.env, ...(options.env ?? {}) },
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
  const ghRepoViewReport = runHelper("gh repo view --json name")
  const dateReport = runHelper('date +"%Y-%m-%d %H:%M"')
  const envBypassReport = runHelper("BASH_ENV=/tmp/evil.sh gh auth status")
  const remoteSetUrlReport = runHelper("git remote set-url origin git@github.com:foo/bar.git")
  const pushReport = runHelper("git push origin main")
  const worktreeAddReport = runHelper("git worktree add ../repo-wt test")
  const branchDeleteReport = runHelper("git branch -d stale-branch")
  const stashPushReport = runHelper("git stash push --include-untracked")
  const ghRepoEditReport = runHelper("gh repo edit --visibility private")

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
  assert.equal(ghRepoViewReport.result, "PASS")
  assert.equal(ghRepoViewReport.mode, "direct_run")
  assert.equal(dateReport.result, "PASS")
  assert.equal(dateReport.mode, "direct_run")
  assert.equal(envBypassReport.result, "FAIL")
  assert.equal(envBypassReport.mode, "maintenance_worktree")
  assert.equal(remoteSetUrlReport.result, "FAIL")
  assert.equal(remoteSetUrlReport.mode, "maintenance_worktree")
  assert.equal(pushReport.result, "FAIL")
  assert.equal(pushReport.mode, "maintenance_worktree")
  assert.equal(worktreeAddReport.result, "FAIL")
  assert.equal(worktreeAddReport.mode, "maintenance_worktree")
  assert.equal(branchDeleteReport.result, "FAIL")
  assert.equal(branchDeleteReport.mode, "maintenance_worktree")
  assert.equal(stashPushReport.result, "FAIL")
  assert.equal(stashPushReport.mode, "maintenance_worktree")
  assert.equal(ghRepoEditReport.result, "FAIL")
  assert.equal(ghRepoEditReport.mode, "maintenance_worktree")
})

test("worktree helper stays aligned with newly allowed read-only git inspection commands", () => {
  const statusArgsReport = runHelper("git status --short --branch")
  const diffArgsReport = runHelper("git diff --stat HEAD~1")
  const logArgsReport = runHelper("git log --oneline -n 5")
  const mergeBaseReport = runHelper("git merge-base HEAD main")
  const revListReport = runHelper("git rev-list --count main..HEAD")
  const showReport = runHelper("git show --stat HEAD")
  const symbolicRefReport = runHelper("git symbolic-ref --short HEAD")
  const branchListReport = runHelper("git branch --list feature/*")
  const worktreeListReport = runHelper("git worktree list --porcelain")

  assert.equal(statusArgsReport.result, "PASS")
  assert.equal(statusArgsReport.mode, "direct_run")
  assert.equal(diffArgsReport.result, "PASS")
  assert.equal(diffArgsReport.mode, "direct_run")
  assert.equal(logArgsReport.result, "PASS")
  assert.equal(logArgsReport.mode, "direct_run")
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

test("worktree helper stays aligned with allowed readonly sqlite inspection commands", () => {
  const tablesReport = runHelper('sqlite3 -readonly "/tmp/runtime.db" ".tables"')
  const pragmaReport = runHelper('sqlite3 -readonly "/tmp/runtime.db" "PRAGMA table_info(session);"')
  const selectReport = runHelper('sqlite3 -readonly "/tmp/runtime.db" "SELECT id, title FROM session"')
  const lowercasePragmaReport = runHelper('sqlite3 -readonly "/tmp/runtime.db" "pragma table_info(session);"')
  const lowercaseSelectReport = runHelper('sqlite3 -readonly "/tmp/runtime.db" "select id, title from session"')
  const mutatingPragmaReport = runHelper('sqlite3 -readonly "/tmp/runtime.db" "PRAGMA journal_mode=WAL;"')

  assert.equal(tablesReport.result, "PASS")
  assert.equal(tablesReport.mode, "direct_run")
  assert.equal(pragmaReport.result, "PASS")
  assert.equal(pragmaReport.mode, "direct_run")
  assert.equal(selectReport.result, "PASS")
  assert.equal(selectReport.mode, "direct_run")
  assert.equal(lowercasePragmaReport.result, "PASS")
  assert.equal(lowercasePragmaReport.mode, "direct_run")
  assert.equal(lowercaseSelectReport.result, "PASS")
  assert.equal(lowercaseSelectReport.mode, "direct_run")
  assert.equal(mutatingPragmaReport.result, "FAIL")
  assert.equal(mutatingPragmaReport.mode, "maintenance_worktree")
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
  assert.match(report.suggested_worktree, /-wt-chore-git-commit-m-msg$/)
  assert.match(report.commands[0], /-wt-chore-git-commit-m-msg HEAD$/)
  assert.match(report.note, /blocked command was not executed/i)
  assert.equal(report.blocked_command, 'git commit -m "msg"')
  assert.equal(report.commands.length, 2)
})

test("worktree helper rejects invalid custom branch suggestions", () => {
  const report = JSON.parse(
    runHelperWithArgs([
      "maintenance",
      "--directory",
      repoDirectory,
      "--branch",
      "bad branch name",
      "--command",
      'git commit -m "msg"',
      "--json",
    ]).stdout,
  )

  assert.equal(report.result, "ERROR")
  assert.equal(report.mode, "invalid_branch")
  assert.equal(report.suggested_branch, "bad branch name")
  assert.match(report.error, /branch is not a valid git branch name/)
})

test("worktree helper accepts valid custom branch suggestions", () => {
  const report = runHelperWithArgs([
    "maintenance",
    "--directory",
    repoDirectory,
    "--branch",
    "chore/valid-branch",
    "--command",
    'git commit -m "msg"',
    "--json",
  ])

  assert.equal(JSON.parse(report.stdout).suggested_branch, "chore/valid-branch")
  assert.equal(report.status, 3)
})

test("worktree helper reports stable errors for missing maintenance directories", () => {
  const missingPath = join(tmpdir(), "worktree-helper-missing-dir")
  rmSync(missingPath, { recursive: true, force: true })

  const report = JSON.parse(
    runHelperWithArgs([
      "maintenance",
      "--directory",
      missingPath,
      "--command",
      'git commit -m "msg"',
      "--json",
    ]).stdout,
  )

  assert.equal(report.result, "ERROR")
  assert.equal(report.mode, "invalid_directory")
  assert.match(report.error, /directory does not exist/)
})

test("worktree helper reports stable errors for non-directory paths", () => {
  const tempRoot = mkdtempSync(join(tmpdir(), "worktree-helper-file-dir-"))
  const filePath = join(tempRoot, "not-a-directory.txt")
  execFileSync("python3", ["-c", `from pathlib import Path; Path(${JSON.stringify(filePath)}).write_text("x", encoding="utf-8")`], {
    encoding: "utf-8",
  })

  try {
    const report = JSON.parse(
      runHelperWithArgs([
        "maintenance",
        "--directory",
        filePath,
        "--command",
        'python3 -c "print(1)"',
        "--execute",
        "--json",
      ]).stdout,
    )

    assert.equal(report.result, "ERROR")
    assert.equal(report.mode, "invalid_directory")
    assert.match(report.error, /directory is not a folder/)
  } finally {
    rmSync(tempRoot, { recursive: true, force: true })
  }
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
      'env CI=456 python3 -c "import os; print(os.environ[\'CI\'])"',
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
      'CI=789 python3 -c "import os; print(os.environ[\'CI\'])"',
      "--execute",
      "--json",
    ]).stdout,
  )

  assert.equal(report.result, "EXECUTED")
  assert.equal(report.returncode, 0)
  assert.equal(report.stdout.trim(), "789")
})

test("worktree helper execute mode supports env unsets", () => {
  const report = JSON.parse(
    runHelperWithArgs([
      "maintenance",
      "--directory",
      repoDirectory,
      "--command",
      'env CI=keep -u CI python3 -c "import os; print(os.environ.get(\'CI\', \'missing\'))"',
      "--execute",
      "--json",
    ]).stdout,
  )

  assert.equal(report.result, "EXECUTED")
  assert.equal(report.returncode, 0)
  assert.equal(report.stdout.trim(), "missing")
})

test("worktree helper execute mode supports long-form env unsets", () => {
  const report = JSON.parse(
    runHelperWithArgs([
      "maintenance",
      "--directory",
      repoDirectory,
      "--command",
      'env CI=keep --unset CI python3 -c "import os; print(os.environ.get(\'CI\', \'missing\'))"',
      "--execute",
      "--json",
    ]).stdout,
  )

  assert.equal(report.result, "EXECUTED")
  assert.equal(report.returncode, 0)
  assert.equal(report.stdout.trim(), "missing")
})

test("worktree helper execute mode supports env option terminator", () => {
  const report = JSON.parse(
    runHelperWithArgs([
      "maintenance",
      "--directory",
      repoDirectory,
      "--command",
      'env CI=kept -- python3 -c "import os; print(os.environ[\'CI\'])"',
      "--execute",
      "--json",
    ]).stdout,
  )

  assert.equal(report.result, "EXECUTED")
  assert.equal(report.returncode, 0)
  assert.equal(report.stdout.trim(), "kept")
})

test("worktree helper execute mode rejects unsupported env flags", () => {
  const report = JSON.parse(
    runHelperWithArgs([
      "maintenance",
      "--directory",
      repoDirectory,
      "--command",
      'env -i python3 -c "print(1)"',
      "--execute",
      "--json",
    ]).stdout,
  )

  assert.equal(report.result, "ERROR")
  assert.match(report.error, /unsupported env option for execute mode: -i/)
})

test("worktree helper execute mode rejects bare unset prefixes without env", () => {
  const shortUnsetReport = JSON.parse(
    runHelperWithArgs([
      "maintenance",
      "--directory",
      repoDirectory,
      "--command",
      '--unset CI python3 -c "print(1)"',
      "--execute",
      "--json",
    ]).stdout,
  )
  const longUnsetReport = JSON.parse(
    runHelperWithArgs([
      "maintenance",
      "--directory",
      repoDirectory,
      "--command",
      '--unset=CI python3 -c "print(1)"',
      "--execute",
      "--json",
    ]).stdout,
  )

  assert.equal(shortUnsetReport.result, "ERROR")
  assert.match(shortUnsetReport.error, /unsupported execute-mode prefix without env: --unset/)
  assert.equal(longUnsetReport.result, "ERROR")
  assert.match(longUnsetReport.error, /unsupported execute-mode prefix without env: --unset=CI/)
})

test("worktree helper execute mode rejects unsafe environment keys", () => {
  const pathOverrideReport = JSON.parse(
    runHelperWithArgs([
      "maintenance",
      "--directory",
      repoDirectory,
      "--command",
      'env PATH=/tmp python3 -c "print(1)"',
      "--execute",
      "--json",
    ]).stdout,
  )
  const unsetPathReport = JSON.parse(
    runHelperWithArgs([
      "maintenance",
      "--directory",
      repoDirectory,
      "--command",
      'env --unset PATH python3 -c "print(1)"',
      "--execute",
      "--json",
    ]).stdout,
  )

  assert.equal(pathOverrideReport.result, "ERROR")
  assert.match(pathOverrideReport.error, /unsupported execute-mode environment key: PATH/)
  assert.equal(unsetPathReport.result, "ERROR")
  assert.match(unsetPathReport.error, /unsupported execute-mode environment key: PATH/)
})

test("worktree helper execute mode reports stable errors for malformed quoting", () => {
  const report = JSON.parse(
    runHelperWithArgs([
      "maintenance",
      "--directory",
      repoDirectory,
      "--command",
      'python3 -c "print(1)',
      "--execute",
      "--json",
    ]).stdout,
  )

  assert.equal(report.result, "ERROR")
  assert.match(report.error, /valid shell-style quoting/)
})

test("worktree helper execute mode times out long-running commands", () => {
  const report = JSON.parse(
    runHelperWithArgs(
      [
        "maintenance",
        "--directory",
        repoDirectory,
        "--command",
        'python3 -c "import time; time.sleep(1); print(123)"',
        "--execute",
        "--json",
      ],
      { env: { OPENCODE_MAINTENANCE_HELPER_EXEC_TIMEOUT: "0.1" } },
    ).stdout,
  )

  assert.equal(report.result, "ERROR")
  assert.match(report.error, /timed out after 0.1s/)
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
    assert.match(report.commands[0], /git -C .* add \.$/)
    assert.match(report.commands[1], /git -C .* commit -m "Initial commit"$/)
    assert.match(report.commands[2], /status --short --branch$/)
  } finally {
    rmSync(tempRoot, { recursive: true, force: true })
  }
})
