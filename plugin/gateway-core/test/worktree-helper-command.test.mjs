import assert from "node:assert/strict"
import { execFileSync } from "node:child_process"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"
import { fileURLToPath } from "node:url"

const helperPath = fileURLToPath(new URL("../../../scripts/worktree_helper_command.py", import.meta.url))
const repoDirectory = fileURLToPath(new URL("../../../", import.meta.url))

const classifierScript = `
import json
import runpy
import sys

classify = runpy.run_path(sys.argv[1], run_name="worktree_helper_command_test")["is_direct_allowed_protected_main_command"]
commands = json.load(sys.stdin)
print(json.dumps([classify(command) for command in commands]))
`

function assertCommandClassifications(cases) {
  const results = JSON.parse(
    execFileSync("python3", ["-c", classifierScript, helperPath], {
      encoding: "utf-8",
      input: JSON.stringify(cases.map(([command]) => command)),
    }),
  )

  assert.equal(results.length, cases.length)
  for (const [index, [command, expected]] of cases.entries()) {
    assert.equal(results[index], expected, `unexpected classification for: ${command}`)
  }
}

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

test("worktree helper tells operators to run allowed oc add commands directly", () => {
  const taskReport = runHelper('oc add task "Improve gateway stall recovery" --scope dmoliveira/my_opencode --kind feature --priority P1')
  const sessionReport = runHelper('oc add session "Implement gateway stall recovery fixes" --task task_112 --worktree . --branch feat/gateway-stall-recovery')

  assert.equal(taskReport.result, "PASS")
  assert.equal(taskReport.mode, "direct_run")
  assert.deepEqual(taskReport.commands, ['oc add task "Improve gateway stall recovery" --scope dmoliveira/my_opencode --kind feature --priority P1'])
  assert.equal(sessionReport.result, "PASS")
  assert.equal(sessionReport.mode, "direct_run")
  assert.deepEqual(sessionReport.commands, ['oc add session "Implement gateway stall recovery fixes" --task task_112 --worktree . --branch feat/gateway-stall-recovery'])
})

test("worktree helper treats direct session doctor and repair commands as protected-main safe guidance", () => {
  const doctorReport = runHelper("python3 scripts/session_command.py doctor --json")
  const repairReport = runHelper("python3 scripts/session_command.py repair-stale --stale-seconds 300 --apply --json")

  assert.equal(doctorReport.result, "PASS")
  assert.equal(doctorReport.mode, "direct_run")
  assert.deepEqual(doctorReport.commands, ["python3 scripts/session_command.py doctor --json"])
  assert.equal(repairReport.result, "PASS")
  assert.equal(repairReport.mode, "direct_run")
  assert.deepEqual(repairReport.commands, ["python3 scripts/session_command.py repair-stale --stale-seconds 300 --apply --json"])
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
  assertCommandClassifications([
    ["git fetch --all --prune --quiet", true],
    ["git fetch --prune origin", true],
    ["git pull --rebase --autostash", true],
    ["git pull --rebase origin main", true],
    ["git merge --no-edit feature-branch", true],
    ["git remote get-url origin", true],
    ["git switch --detach origin/main", true],
    ["git checkout --detach main", true],
    ["git restore --source main -- README.md", true],
    ["git checkout main -- README.md", true],
    ["git stash list", true],
    ["pwd", true],
    ["ls -la", true],
    ["make validate", true],
    ["npm install --yes", true],
    ["npm ci --yes --no-audit --no-fund", true],
    ["npm init -y", true],
    ["npm test", true],
    ["pnpm test", true],
    ["yarn lint", true],
    ["bun run build", true],
    ["python3 -m pytest tests/test_sample.py", true],
    ["node --test test/worktree-helper-command.test.mjs", true],
    ["pre-commit run --files scripts/worktree_helper_command.py", true],
    ["eslint src/index.ts", true],
    ["tsc -p tsconfig.json", true],
    ["ruff check src", true],
    ["gh auth status", true],
    ["gh pr view --json number", true],
    ["gh repo view --json name", true],
    ['date +"%Y-%m-%d %H:%M"', true],
    ["BASH_ENV=/tmp/evil.sh gh auth status", false],
    ["git remote set-url origin git@github.com:foo/bar.git", true],
    ["git push origin main", true],
    ["git worktree add ../repo-wt test", true],
    ["git branch -d stale-branch", true],
    ["git stash push --include-untracked", true],
    ["gh repo edit --visibility private", true],
  ])
})

test("worktree helper keeps direct-run guidance for wrapper and env-prefixed safe commands", () => {
  assertCommandClassifications([
    ["rtk git status --short --branch", true],
    ["/usr/bin/git diff --stat HEAD~1", true],
    ["git --no-pager log --oneline -n 1", true],
    [`git -C ${repoDirectory} status --short --branch`, true],
    ["rtk gh pr view --json number", true],
    ["env CI=true gh auth status", true],
    ["env GIT_PAGER=cat git log --oneline -n 1", true],
  ])
})

test("worktree helper stays aligned with newly allowed read-only git inspection commands", () => {
  assertCommandClassifications([
    ["git status --short --branch", true],
    ["git diff --stat HEAD~1", true],
    ["git log --oneline -n 5", true],
    ["git diff --output=/tmp/worktree-helper-out", false],
    ["git diff --ext-diff HEAD~1", false],
    ["git show --textconv HEAD", false],
    ["git merge-base HEAD main", true],
    ["git rev-list --count main..HEAD", true],
    ["git show --stat HEAD", true],
    ["git symbolic-ref --short HEAD", true],
    ["git branch --list feature/*", true],
    ["git worktree list --porcelain", true],
  ])
})

test("worktree helper stays aligned with allowed readonly sqlite inspection commands", () => {
  assertCommandClassifications([
    ['sqlite3 -readonly "/tmp/runtime.db" ".tables"', true],
    ['sqlite3 -readonly "/tmp/runtime.db" "PRAGMA table_info(session);"', true],
    ['sqlite3 -readonly "/tmp/runtime.db" "SELECT id, title FROM session"', true],
    ['sqlite3 -readonly "/tmp/runtime.db" "WITH hits AS (SELECT 1 AS id) SELECT id FROM hits;"', true],
    ['sqlite3 -readonly "/tmp/runtime.db" "pragma table_info(session);"', true],
    ['sqlite3 -readonly "/tmp/runtime.db" "select id, title from session"', true],
    ['sqlite3 -readonly "/tmp/runtime.db" "PRAGMA journal_mode=WAL;"', false],
    [
      `sqlite3 -readonly "/tmp/runtime.db" "SELECT 1
.shell touch /tmp/pwn"`,
      false,
    ],
  ])
})

test("worktree helper treats chained oc status bundles as direct-run safe guidance", () => {
  const report = runHelper("oc current || true; printf '\n---\n'; oc next || true; printf '\n---\n'; oc queue || true")

  assert.equal(report.result, "PASS")
  assert.equal(report.mode, "direct_run")
  assert.deepEqual(report.commands, ["oc current || true; printf '\n---\n'; oc next || true; printf '\n---\n'; oc queue || true"])
})

test("worktree helper keeps unsafe oc bundle syntax blocked", () => {
  const report = runHelper("oc current > /tmp/out || true")

  assert.equal(report.result, "FAIL")
  assert.equal(report.mode, "maintenance_worktree")
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

test("worktree helper generates distinct hashed suggestions for colliding long commands", () => {
  const commandA = 'git commit -m "this-is-a-very-long-command-name-that-forces-a-collision-prefix-aaaaaaaa"'
  const commandB = 'git commit -m "this-is-a-very-long-command-name-that-forces-a-collision-prefix-bbbbbbbb"'
  const reportA = runHelper(commandA)
  const reportB = runHelper(commandB)

  assert.equal(reportA.result, "FAIL")
  assert.equal(reportB.result, "FAIL")
  assert.notEqual(reportA.suggested_branch, reportB.suggested_branch)
  assert.notEqual(reportA.suggested_worktree, reportB.suggested_worktree)
  assert.match(reportA.suggested_branch, /^chore\/.*-[0-9a-f]{8}$/)
  assert.match(reportB.suggested_branch, /^chore\/.*-[0-9a-f]{8}$/)
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

test("worktree helper reports stable errors for non-git directories", () => {
  const tempRoot = mkdtempSync(join(tmpdir(), "worktree-helper-non-git-"))

  try {
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

    assert.equal(report.result, "ERROR")
    assert.equal(report.mode, "invalid_repository")
    assert.match(report.error, /directory is not a git repository/)
  } finally {
    rmSync(tempRoot, { recursive: true, force: true })
  }
})

test("worktree helper reports stable errors for empty commands", () => {
  const previewReport = JSON.parse(
    runHelperWithArgs([
      "maintenance",
      "--directory",
      repoDirectory,
      "--command",
      "   ",
      "--json",
    ]).stdout,
  )
  const executeReport = JSON.parse(
    runHelperWithArgs([
      "maintenance",
      "--directory",
      repoDirectory,
      "--command",
      "   ",
      "--execute",
      "--json",
    ]).stdout,
  )

  assert.equal(previewReport.result, "ERROR")
  assert.equal(previewReport.mode, "invalid_command")
  assert.match(previewReport.error, /command must not be empty/)
  assert.equal(executeReport.result, "ERROR")
  assert.equal(executeReport.mode, "invalid_command")
  assert.match(executeReport.error, /command must not be empty/)
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
  assert.equal(report.mode, "execute_run")
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
  assert.equal(report.mode, "execute_run")
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
  assert.equal(report.mode, "execute_run")
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
  assert.equal(report.mode, "execute_run")
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
  assert.equal(report.mode, "execute_run")
  assert.equal(report.returncode, 0)
  assert.equal(report.stdout.trim(), "missing")
})

test("worktree helper execute mode supports compact env unset syntax", () => {
  const report = JSON.parse(
    runHelperWithArgs([
      "maintenance",
      "--directory",
      repoDirectory,
      "--command",
      'env CI=keep --unset=CI python3 -c "import os; print(os.environ.get(\'CI\', \'missing\'))"',
      "--execute",
      "--json",
    ]).stdout,
  )

  assert.equal(report.result, "EXECUTED")
  assert.equal(report.mode, "execute_run")
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
  assert.equal(report.mode, "execute_run")
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
  assert.equal(report.mode, "execute_error")
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
  assert.equal(shortUnsetReport.mode, "execute_error")
  assert.match(shortUnsetReport.error, /unsupported execute-mode prefix without env: --unset/)
  assert.equal(longUnsetReport.result, "ERROR")
  assert.equal(longUnsetReport.mode, "execute_error")
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
  assert.equal(pathOverrideReport.mode, "execute_error")
  assert.match(pathOverrideReport.error, /unsupported execute-mode environment key: PATH/)
  assert.equal(unsetPathReport.result, "ERROR")
  assert.equal(unsetPathReport.mode, "execute_error")
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
  assert.equal(report.mode, "execute_error")
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
  assert.equal(report.mode, "execute_timeout")
  assert.match(report.error, /timed out after 0.1s/)
})

test("worktree helper execute mode rejects non-finite timeout values", () => {
  const nanReport = JSON.parse(
    runHelperWithArgs(
      [
        "maintenance",
        "--directory",
        repoDirectory,
        "--command",
        'python3 -c "print(123)"',
        "--execute",
        "--json",
      ],
      { env: { OPENCODE_MAINTENANCE_HELPER_EXEC_TIMEOUT: "NaN" } },
    ).stdout,
  )
  const infReport = JSON.parse(
    runHelperWithArgs(
      [
        "maintenance",
        "--directory",
        repoDirectory,
        "--command",
        'python3 -c "print(123)"',
        "--execute",
        "--json",
      ],
      { env: { OPENCODE_MAINTENANCE_HELPER_EXEC_TIMEOUT: "inf" } },
    ).stdout,
  )

  assert.equal(nanReport.result, "ERROR")
  assert.equal(nanReport.mode, "execute_error")
  assert.match(nanReport.error, /must be a finite number/)
  assert.equal(infReport.result, "ERROR")
  assert.equal(infReport.mode, "execute_error")
  assert.match(infReport.error, /must be a finite number/)
})

test("worktree helper execute mode closes stdin for input-reading commands", () => {
  const report = JSON.parse(
    runHelperWithArgs([
      "maintenance",
      "--directory",
      repoDirectory,
      "--command",
      'python3 -c "input()"',
      "--execute",
      "--json",
    ]).stdout,
  )

  assert.equal(report.result, "EXECUTED")
  assert.equal(report.mode, "execute_run")
  assert.equal(report.returncode, 1)
  assert.match(report.stderr, /EOF when reading a line/)
})

test("worktree helper execute mode preserves direct-run guidance for allowed commands", () => {
  const report = JSON.parse(
    runHelperWithArgs([
      "maintenance",
      "--directory",
      repoDirectory,
      "--command",
      'oc done task_175 --note "completed"',
      "--execute",
      "--json",
    ]).stdout,
  )

  assert.equal(report.result, "PASS")
  assert.equal(report.mode, "direct_run")
  assert.deepEqual(report.commands, ['oc done task_175 --note "completed"'])
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
  assert.equal(report.mode, "execute_error")
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
  assert.equal(redirectReport.mode, "execute_error")
  assert.match(redirectReport.error, /single command without shell chaining or redirection/)
  assert.equal(pipelineReport.result, "ERROR")
  assert.equal(pipelineReport.mode, "execute_error")
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
