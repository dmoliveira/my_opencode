import assert from "node:assert/strict"
import { execSync } from "node:child_process"
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join, relative } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

function commitAll(directory, message) {
  execSync("git add .", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
  execSync(`git -c user.name=test -c user.email=test@example.com commit -m "${message}"`, {
    cwd: directory,
    stdio: ["ignore", "pipe", "pipe"],
  })
}

function readAuditEntries(directory) {
  return readFileSync(join(directory, ".opencode", "gateway-events.jsonl"), "utf-8")
    .split(/\r?\n/)
    .filter(Boolean)
    .map((line) => JSON.parse(line))
}

test("workflow-conformance-guard reroutes git commit on protected branch", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-workflow-guard-"))
  const previousAudit = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
  const previousOtel = process.env.MY_OPENCODE_OTEL_EXPORT_ENABLED
  process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = "1"
  process.env.MY_OPENCODE_OTEL_EXPORT_ENABLED = "0"
  try {
    execSync("git init -b main", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: { enabled: true, order: ["workflow-conformance-guard"], disabled: [] },
        workflowConformanceGuard: {
          enabled: true,
          protectedBranches: ["main"],
          blockEditsOnProtectedBranches: true,
        },
      },
    })

    const payload = { args: { command: "git commit -m \"msg\"" } }
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow" },
      payload,
    )
    assert.match(payload.args.command, /python3 ['"].*scripts\/worktree_helper_command\.py['"] maintenance --directory/)
    assert.match(payload.args.command, /--command 'git commit -m "msg"' --json/)
    assert.ok(
      readAuditEntries(directory).some(
        (entry) =>
          entry.hook === "workflow-conformance-guard" &&
          entry.reason_code === "commit_on_protected_branch_rerouted",
      ),
    )
  } finally {
    if (previousAudit === undefined) {
      delete process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
    } else {
      process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = previousAudit
    }
    if (previousOtel === undefined) {
      delete process.env.MY_OPENCODE_OTEL_EXPORT_ENABLED
    } else {
      process.env.MY_OPENCODE_OTEL_EXPORT_ENABLED = previousOtel
    }
    rmSync(directory, { recursive: true, force: true })
  }
})

test("workflow-conformance-guard blocks file edits on protected branch", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-workflow-guard-"))
  try {
    execSync("git init -b main", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: { enabled: true, order: ["workflow-conformance-guard"], disabled: [] },
        workflowConformanceGuard: {
          enabled: true,
          protectedBranches: ["main"],
          blockEditsOnProtectedBranches: true,
        },
      },
    })

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "write", sessionID: "session-workflow-edit" },
        { args: { filePath: "src/new.ts" } },
      ),
      /File edits are blocked on protected branch/,
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("workflow-conformance-guard blocks direct maintenance-helper execute mode on protected branch", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-workflow-guard-"))
  try {
    execSync("git init -b main", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: { enabled: true, order: ["workflow-conformance-guard"], disabled: [] },
        workflowConformanceGuard: {
          enabled: true,
          protectedBranches: ["main"],
          blockEditsOnProtectedBranches: true,
        },
      },
    })

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "bash", sessionID: "session-workflow-maintenance-helper-execute" },
        {
          args: {
            command:
              'python3 scripts/worktree_helper_command.py maintenance --directory . --command "git commit -m \'msg\'" --execute --json',
          },
        },
      ),
      /Direct maintenance-helper execute mode is blocked on protected branch 'main'/,
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("workflow-conformance-guard keeps an allowed bash command unchanged on protected branches", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-workflow-guard-"))
  try {
    execSync("git init -b main", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: { enabled: true, order: ["workflow-conformance-guard"], disabled: [] },
        workflowConformanceGuard: {
          enabled: true,
          protectedBranches: ["main"],
          blockEditsOnProtectedBranches: true,
        },
      },
    })
    const command =
      "CI=true GIT_TERMINAL_PROMPT=0 GIT_EDITOR=true GIT_PAGER=cat PAGER=cat GCM_INTERACTIVE=never git --no-pager log --oneline --decorate --graph -20"
    const payload = { args: { command } }

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-safe" },
      payload,
    )

    assert.equal(payload.args.command, command)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("workflow-conformance-guard reroutes env-prefixed git mutation commands", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-workflow-guard-"))
  try {
    execSync("git init -b main", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: { enabled: true, order: ["workflow-conformance-guard"], disabled: [] },
        workflowConformanceGuard: {
          enabled: true,
          protectedBranches: ["main"],
          blockEditsOnProtectedBranches: true,
        },
      },
    })

    const payload = { args: { command: "env GIT_TRACE=1 git commit -m \"msg\"" } }
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-env" },
      payload
    )
    assert.match(payload.args.command, /python3 ['"].*scripts\/worktree_helper_command\.py['"] maintenance --directory/)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("workflow-conformance-guard reroutes wrapped rtk git commit on protected branch", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-workflow-guard-"))
  try {
    execSync("git init -b main", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: { enabled: true, order: ["workflow-conformance-guard"], disabled: [] },
        workflowConformanceGuard: {
          enabled: true,
          protectedBranches: ["main"],
          blockEditsOnProtectedBranches: true,
        },
      },
    })

    const payload = { args: { command: 'rtk git commit -m "msg"' } }
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-workflow-rtk-commit" },
      payload,
    )
    assert.match(payload.args.command, /python3 ['"].*scripts\/worktree_helper_command\.py['"] maintenance --directory/)
    assert.match(payload.args.command, /--command 'rtk git commit -m "msg"' --json/)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("workflow-conformance-guard allows apply_patch targeting a linked worktree from protected main", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-workflow-guard-"))
  const linked = `${directory}-linked`
  try {
    execSync("git init -b main", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
    writeFileSync(join(directory, "file.txt"), "v1\n", "utf-8")
    commitAll(directory, "init")
    execSync("git checkout -b feature", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
    execSync(`git worktree add "${linked}" main`, { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })

    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["primary-worktree-guard", "workflow-conformance-guard"],
          disabled: [],
        },
        primaryWorktreeGuard: {
          enabled: true,
          allowedBranches: ["main", "master"],
          blockEdits: true,
          blockBranchSwitches: true,
        },
        workflowConformanceGuard: {
          enabled: true,
          protectedBranches: ["main"],
          blockEditsOnProtectedBranches: true,
        },
      },
    })

    await plugin["tool.execute.before"](
      { tool: "apply_patch", sessionID: "session-protected-dir-linked-patch", directory },
      {
        args: {
          patchText: `*** Begin Patch
*** Add File: ${join(linked, "src/new.ts")}
+export const value = 1
*** End Patch`,
        },
      }
    )
    await plugin["tool.execute.before"](
      { tool: "apply_patch", sessionID: "session-protected-dir-linked-patch-relative", directory },
      {
        args: {
          patchText: `*** Begin Patch
*** Add File: ${relative(directory, join(linked, "src/relative.ts"))}
+export const relativeValue = 1
*** End Patch`,
        },
      }
    )
  } finally {
    rmSync(linked, { recursive: true, force: true })
    rmSync(directory, { recursive: true, force: true })
  }
})

test("workflow-conformance-guard reroutes representative unsafe bash commands on protected branches", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-workflow-guard-"))
  const previousAudit = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
  const previousOtel = process.env.MY_OPENCODE_OTEL_EXPORT_ENABLED
  process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = "1"
  process.env.MY_OPENCODE_OTEL_EXPORT_ENABLED = "0"
  try {
    execSync("git init -b main", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: { enabled: true, order: ["workflow-conformance-guard"], disabled: [] },
        workflowConformanceGuard: {
          enabled: true,
          protectedBranches: ["main"],
          blockEditsOnProtectedBranches: true,
        },
      },
    })
    const cases = [
      ["session-workflow-bash-mutate", "echo hi > file.txt"],
      ["session-workflow-command-substitution", 'git status --short --branch "$(touch /tmp/pwn)"'],
      ["session-workflow-env-expansion", 'CI="$(id)" git fetch'],
      [
        "session-workflow-sqlite-env-bypass",
        'BASH_ENV=/tmp/evil.sh sqlite3 -readonly "/tmp/runtime.db" ".tables"',
      ],
    ]

    for (const [sessionID, command] of cases) {
      const payload = { args: { command } }
      await plugin["tool.execute.before"]({ tool: "bash", sessionID }, payload)
      assert.match(
        payload.args.command,
        /python3 ['"].*scripts\/worktree_helper_command\.py['"] maintenance --directory/,
      )
      assert.ok(
        payload.args.command.includes(`--command '${command}' --json`),
        `expected exact shell-quoted command: ${command}`,
      )
    }
    assert.ok(
      readAuditEntries(directory).some(
        (entry) =>
          entry.hook === "workflow-conformance-guard" &&
          entry.reason_code === "bash_on_protected_branch_rerouted",
      ),
    )
  } finally {
    if (previousAudit === undefined) {
      delete process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
    } else {
      process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = previousAudit
    }
    if (previousOtel === undefined) {
      delete process.env.MY_OPENCODE_OTEL_EXPORT_ENABLED
    } else {
      process.env.MY_OPENCODE_OTEL_EXPORT_ENABLED = previousOtel
    }
    rmSync(directory, { recursive: true, force: true })
  }
})

test("combined protected-main guards do not double-wrap maintenance helper reroutes", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-workflow-guard-"))
  try {
    execSync("git init -b main", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: { enabled: true, order: ["primary-worktree-guard", "workflow-conformance-guard"], disabled: [] },
        primaryWorktreeGuard: {
          enabled: true,
          allowedBranches: ["main", "master"],
          blockEdits: true,
          blockBranchSwitches: true,
        },
        workflowConformanceGuard: {
          enabled: true,
          protectedBranches: ["main"],
          blockEditsOnProtectedBranches: true,
        },
      },
    })

    const payload = { args: { command: 'git commit -m "msg"' } }
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-combined-reroute-dedupe" },
      payload,
    )

    assert.match(payload.args.command, /python3 ['"].*scripts\/worktree_helper_command\.py['"] maintenance --directory/)
    assert.equal((payload.args.command.match(/worktree_helper_command\.py/g) ?? []).length, 1)
    assert.match(payload.args.command, /--command 'git commit -m "msg"' --json/)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("workflow-conformance-guard explains reroute failures when helper path is missing", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-workflow-guard-"))
  const originalHelper = process.env.OPENCODE_MAINTENANCE_HELPER_PATH
  process.env.OPENCODE_MAINTENANCE_HELPER_PATH = join(directory, "missing-helper.py")
  try {
    execSync("git init -b main", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: { enabled: true, order: ["workflow-conformance-guard"], disabled: [] },
        workflowConformanceGuard: {
          enabled: true,
          protectedBranches: ["main"],
          blockEditsOnProtectedBranches: true,
        },
      },
    })

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "bash", sessionID: "session-workflow-helper-missing" },
        { args: { command: 'git commit -m "msg"' } },
      ),
      /Intended reroute:/,
    )
  } finally {
    if (originalHelper === undefined) {
      delete process.env.OPENCODE_MAINTENANCE_HELPER_PATH
    } else {
      process.env.OPENCODE_MAINTENANCE_HELPER_PATH = originalHelper
    }
    rmSync(directory, { recursive: true, force: true })
  }
})

test("workflow-conformance-guard allows linked worktree edits even when the linked branch is main", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-workflow-guard-"))
  const linked = `${directory}-linked`
  try {
    execSync("git init -b main", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
    writeFileSync(join(directory, "file.txt"), "v1\n", "utf-8")
    commitAll(directory, "init")
    execSync("git checkout -b feature", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
    execSync(`git worktree add "${linked}" main`, { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })

    const plugin = GatewayCorePlugin({
      directory: linked,
      config: {
        hooks: {
          enabled: true,
          order: ["primary-worktree-guard", "workflow-conformance-guard"],
          disabled: [],
        },
        primaryWorktreeGuard: {
          enabled: true,
          allowedBranches: ["main", "master"],
          blockEdits: true,
          blockBranchSwitches: true,
        },
        workflowConformanceGuard: {
          enabled: true,
          protectedBranches: ["main"],
          blockEditsOnProtectedBranches: true,
        },
      },
    })

    await plugin["tool.execute.before"](
      { tool: "write", sessionID: "session-linked-protected-edit" },
      { args: { filePath: "src/new.ts" } }
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-linked-protected-sync" },
      { args: { command: "git pull --rebase" } }
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-linked-protected-fetch" },
      { args: { command: "git fetch --prune" } }
    )
  } finally {
    rmSync(linked, { recursive: true, force: true })
    rmSync(directory, { recursive: true, force: true })
  }
})

test("workflow-conformance-guard allows linked worktree targets when session directory is protected main", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-workflow-guard-"))
  const linked = `${directory}-linked`
  try {
    execSync("git init -b main", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
    writeFileSync(join(directory, "file.txt"), "v1\n", "utf-8")
    commitAll(directory, "init")
    execSync("git checkout -b feature", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
    execSync(`git worktree add "${linked}" main`, { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })

    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["primary-worktree-guard", "workflow-conformance-guard"],
          disabled: [],
        },
        primaryWorktreeGuard: {
          enabled: true,
          allowedBranches: ["main", "master"],
          blockEdits: true,
          blockBranchSwitches: true,
        },
        workflowConformanceGuard: {
          enabled: true,
          protectedBranches: ["main"],
          blockEditsOnProtectedBranches: true,
        },
      },
    })

    await plugin["tool.execute.before"](
      { tool: "write", sessionID: "session-protected-dir-linked-write", directory },
      { args: { filePath: join(linked, "src/new.ts") } }
    )
    await plugin["tool.execute.before"](
      { tool: "write", sessionID: "session-protected-dir-linked-write-relative", directory },
      { args: { filePath: relative(directory, join(linked, "src/new.ts")) } }
    )
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-protected-dir-linked-bash", directory },
      { args: { command: "git status --short --branch", workdir: linked } }
    )
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-protected-dir-linked-bash-relative", directory },
      { args: { command: "git status --short --branch", workdir: relative(directory, linked) } }
    )
  } finally {
    rmSync(linked, { recursive: true, force: true })
    rmSync(directory, { recursive: true, force: true })
  }
})
