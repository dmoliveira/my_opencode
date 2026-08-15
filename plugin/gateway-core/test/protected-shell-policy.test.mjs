import assert from "node:assert/strict"
import test from "node:test"

import { isAllowedProtectedShellCommand } from "../dist/hooks/protected-shell-policy.js"

const allowedCommands = [
  "git status --short --branch",
  "rtk git status --short --branch",
  "git --no-pager log --oneline --decorate --graph -20",
  "git --no-pager status --short --branch",
  'git -C "/tmp/repo" worktree list',
  '/usr/bin/git -C "/tmp/repo" worktree list',
  "CI=true GIT_TERMINAL_PROMPT=0 GIT_EDITOR=true GIT_PAGER=cat PAGER=cat GCM_INTERACTIVE=never git --no-pager log --oneline --decorate --graph -20",
  'sqlite3 -readonly "/tmp/runtime.db" ".tables"',
  'sqlite3 -readonly "/tmp/runtime.db" ".schema session"',
  'CI=true OPENCODE_SESSION_ID=demo sqlite3 -readonly "/tmp/runtime.db" "PRAGMA table_info(session);"',
  'sqlite3 -readonly "/tmp/runtime.db" "SELECT id, title FROM session"',
  'sqlite3 -readonly "/tmp/runtime.db" "WITH hits AS (SELECT 1 AS id) SELECT id FROM hits;"',
  "oc current || true; printf '\n---\n'; oc next || true; printf '\n---\n'; oc queue || true",
  "/usr/bin/gh pr view --json number",
  "git fetch",
  "git fetch --prune",
  "git fetch --prune origin",
  "git fetch --all --prune --quiet",
  "git remote -v",
  "git remote get-url origin",
  "git remote add origin https://github.com/foo/bar.git",
  "git remote set-url origin git@github.com:foo/bar.git",
  "git merge-base HEAD main",
  "git rev-list --count main..HEAD",
  "git show --stat HEAD",
  "git symbolic-ref --short HEAD",
  "git switch --detach origin/main",
  "git push -u origin main",
  "git pull --rebase --autostash",
  "git pull --rebase origin main",
  "git merge --no-edit feature/test",
  "git merge --ff-only origin/main",
  'git worktree add -b feature/test "/tmp/gateway-linked" origin/main',
  'git worktree remove "/tmp/gateway-linked"',
  "git branch -d feature/test",
  'git worktree remove "/tmp/gateway-linked" && git branch -d feature/test',
  'git stash push -m "temp" -- docs/plan/docs-automation-summary.md',
  "git stash list",
  "git stash list && git status --short --branch",
  "git restore --source main -- docs/plan/docs-automation-summary.md",
  "git checkout main -- docs/plan/docs-automation-summary.md",
  "oc current",
  "oc next",
  "oc queue",
  "oc next --scope dmoliveira/my_opencode --limit 5",
  "oc queue --scope dmoliveira/my_opencode --limit 10",
  "oc current --format json",
  "oc resume --task task_171",
  'oc done task_171 --note "completed"',
  'oc end-session --outcome done session_62 --achievements "cleanup complete"',
  "oc add task 'plan; validate & close | archive'",
  "oc add session 'plan; validate & close | archive'",
  "oc resume --task 'task_171;validate&close|archive'",
  "oc done task_171 --note 'validated; closeout & handoff | complete'",
  "oc end-session --outcome done session_62 --achievements 'validated; closeout & handoff | complete'",
  "git branch -r --contains origin/main",
  "gh auth status",
  "gh repo view --json nameWithOwner",
  "gh repo create foo/bar --private --source . --remote origin --push",
  "gh repo edit --visibility private",
  "gh api user",
  'date +"%Y-%m-%d %H:%M"',
  "npm install --yes",
  "npm ci --yes --no-audit --no-fund",
  "npm init -y",
  'oc add task "Improve gateway stall recovery" --scope dmoliveira/my_opencode --kind feature --priority P1',
  'oc add session "Implement gateway stall recovery fixes" --task task_112 --worktree . --branch feat/gateway-stall-recovery',
  "python3 scripts/session_command.py doctor --json",
  "python3 scripts/session_command.py repair-sidecars --apply --json",
  "python3 scripts/session_command.py repair-runtime-permissions --apply --json",
  "python3 scripts/session_command.py repair-stale --stale-seconds 300 --apply --json",
]

const blockedCommands = [
  "npm install --yes --prefix /tmp/other-project",
  "echo hi > file.txt",
  "gh api -X POST repos/foo/bar/issues",
  "git status --short --branch && echo hi > file.txt",
  "git pull --rebase origin feature/x",
  "git fetch origin +feature/x:main",
  "git stash pop",
  "git status --short --branch > file.txt",
  'git status --short --branch "$(touch /tmp/pwn)"',
  'CI="$(id)" git fetch',
  'sqlite3 -readonly "/tmp/runtime.db" -cmd ".shell touch /tmp/pwn" ".tables"',
  'sqlite3 -readonly "/tmp/runtime.db" ".output /tmp/dump.txt"',
  'sqlite3 -readonly "/tmp/runtime.db" "PRAGMA journal_mode=WAL;"',
  'sqlite3 -readonly "/tmp/runtime.db" "WITH recent AS (SELECT 1) INSERT INTO audit_log SELECT * FROM recent;"',
  'sqlite3 -readonly "/tmp/runtime.db" "SELECT 1; DELETE FROM audit_log;"',
  'sqlite3 -readonly "/tmp/runtime.db" "PRAGMA table_info(session); INSERT INTO audit_log VALUES (1);"',
  'sqlite3 -readonly "/tmp/runtime.db" "SELECT load_extension(\"/tmp/pwn\");"',
  'BASH_ENV=/tmp/evil.sh sqlite3 -readonly "/tmp/runtime.db" ".tables"',
  `sqlite3 -readonly "/tmp/runtime.db" "SELECT 1
.shell touch /tmp/pwn"`,
  "oc current > /tmp/out || true",
  "git fetch --upload-pack=/tmp/evil origin",
  "oc end-session --outcome done session_62 --achievements validated; touch /tmp/pwn",
  "oc end-session --outcome done session_62 --achievements validated & touch /tmp/pwn",
  "oc end-session --outcome done session_62 --achievements validated | touch /tmp/pwn",
  "oc end-session --outcome done session_62 --achievements validated > /tmp/pwn",
  'oc end-session --outcome done session_62 --achievements "$(touch /tmp/pwn)"',
  "oc end-session --outcome done session_62 --achievements '${HOME}'",
  'oc end-session --outcome done session_62 --achievements "$$"',
  'oc end-session --outcome done session_62 --achievements "$?"',
  'oc end-session --outcome done session_62 --achievements "$0"',
  'oc end-session --outcome done session_62 --achievements "$@"',
  "oc end-session --outcome done session_62 --achievements 'unterminated",
  'oc end-session --outcome done session_62 --achievements "unterminated',
]

test("protected shell policy allows the complete guard command inventory", () => {
  assert.equal(allowedCommands.length, 71)
  assert.equal(new Set(allowedCommands).size, allowedCommands.length)
  for (const command of allowedCommands) {
    assert.equal(isAllowedProtectedShellCommand(command), true, `expected allowed: ${command}`)
  }
})

test("protected shell policy blocks the complete guard command inventory", () => {
  assert.equal(blockedCommands.length, 33)
  assert.equal(new Set(blockedCommands).size, blockedCommands.length)
  for (const command of blockedCommands) {
    assert.equal(isAllowedProtectedShellCommand(command), false, `expected blocked: ${command}`)
  }
})
