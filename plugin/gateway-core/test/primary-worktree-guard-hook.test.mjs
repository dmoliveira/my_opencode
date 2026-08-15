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

test("primary-worktree-guard blocks file edits in the primary worktree", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-primary-worktree-"))
  try {
    execSync("git init -b main", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
    writeFileSync(join(directory, "file.txt"), "v1\n", "utf-8")
    commitAll(directory, "init")
    execSync("git checkout -b feature", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })

    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: { enabled: true, order: ["primary-worktree-guard"], disabled: [] },
        primaryWorktreeGuard: {
          enabled: true,
          allowedBranches: ["main", "master"],
          blockEdits: true,
          blockBranchSwitches: true,
        },
      },
    })

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "write", sessionID: "session-primary-edit" },
        { args: { filePath: "src/new.ts" } }
      ),
      /primary project folder/
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("primary-worktree-guard blocks switching the primary worktree onto task branches", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-primary-worktree-"))
  try {
    execSync("git init -b main", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
    writeFileSync(join(directory, "file.txt"), "v1\n", "utf-8")
    commitAll(directory, "init")

    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: { enabled: true, order: ["primary-worktree-guard"], disabled: [] },
        primaryWorktreeGuard: {
          enabled: true,
          allowedBranches: ["main", "master"],
          blockEdits: true,
          blockBranchSwitches: true,
        },
      },
    })

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "bash", sessionID: "session-primary-branch-hop" },
        { args: { command: "git switch feature/foo" } }
      ),
      /Branch switching to 'feature\/foo' is blocked/
    )

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "bash", sessionID: "session-primary-branch-hop-abs" },
        { args: { command: "/usr/bin/git switch feature/bar" } }
      ),
      /Branch switching to 'feature\/bar' is blocked/
    )

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "bash", sessionID: "session-primary-branch-hop-env" },
        { args: { command: "env GIT_TRACE=1 git switch feature/baz" } }
      ),
      /Branch switching to 'feature\/baz' is blocked/
    )

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "bash", sessionID: "session-primary-branch-hop-rtk" },
        { args: { command: "rtk git switch feature/qux" } }
      ),
      /Branch switching to 'feature\/qux' is blocked/
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-branch-allowed" },
      { args: { command: "git switch main" } }
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-branch-allowed-rtk" },
      { args: { command: "rtk git switch main" } }
    )

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "bash", sessionID: "session-primary-branch-reset" },
        { args: { command: "git switch -C main" } }
      ),
      /Branch switching to 'main' is blocked/
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-checkout-path" },
      { args: { command: "git checkout main -- file.txt" } }
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-branch-detach-main" },
      { args: { command: "git switch --detach origin/main" } }
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-branch-detach-main-checkout" },
      { args: { command: "git checkout --detach main" } }
    )

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "bash", sessionID: "session-primary-maintenance-helper-execute" },
        {
          args: {
            command:
              'python3 scripts/worktree_helper_command.py maintenance --directory . --command "git commit -m \'msg\'" --execute --json',
          },
        }
      ),
      /Direct maintenance-helper execute mode is blocked in the primary project folder/
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("primary-worktree-guard allows edits in linked worktrees", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-primary-worktree-"))
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
        hooks: { enabled: true, order: ["primary-worktree-guard"], disabled: [] },
        primaryWorktreeGuard: {
          enabled: true,
          allowedBranches: ["main", "master"],
          blockEdits: true,
          blockBranchSwitches: true,
        },
      },
    })

    await plugin["tool.execute.before"](
      { tool: "write", sessionID: "session-linked-edit" },
      { args: { filePath: "src/new.ts" } }
    )
  } finally {
    rmSync(linked, { recursive: true, force: true })
    rmSync(directory, { recursive: true, force: true })
  }
})

test("primary-worktree-guard allows linked worktree targets even when session directory is the primary worktree", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-primary-worktree-"))
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
        hooks: { enabled: true, order: ["primary-worktree-guard"], disabled: [] },
        primaryWorktreeGuard: {
          enabled: true,
          allowedBranches: ["main", "master"],
          blockEdits: true,
          blockBranchSwitches: true,
        },
      },
    })

    await plugin["tool.execute.before"](
      { tool: "write", sessionID: "session-primary-dir-linked-write", directory },
      { args: { filePath: join(linked, "src/new.ts") } }
    )
    await plugin["tool.execute.before"](
      { tool: "write", sessionID: "session-primary-dir-linked-write-relative", directory },
      { args: { filePath: relative(directory, join(linked, "src/new.ts")) } }
    )
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-dir-linked-bash", directory },
      { args: { command: "git status --short --branch", workdir: linked } }
    )
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-dir-linked-bash-relative", directory },
      { args: { command: "git status --short --branch", workdir: relative(directory, linked) } }
    )
  } finally {
    rmSync(linked, { recursive: true, force: true })
    rmSync(directory, { recursive: true, force: true })
  }
})

test("primary-worktree-guard allows apply_patch targeting a linked worktree from the primary worktree", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-primary-worktree-"))
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
        hooks: { enabled: true, order: ["primary-worktree-guard"], disabled: [] },
        primaryWorktreeGuard: {
          enabled: true,
          allowedBranches: ["main", "master"],
          blockEdits: true,
          blockBranchSwitches: true,
        },
      },
    })

    await plugin["tool.execute.before"](
      { tool: "apply_patch", sessionID: "session-primary-dir-linked-patch", directory },
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
      { tool: "apply_patch", sessionID: "session-primary-dir-linked-patch-relative", directory },
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

test("primary-worktree-guard preserves representative allow, reroute, and branch-switch behavior", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-primary-worktree-"))
  const previousAudit = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
  const previousOtel = process.env.MY_OPENCODE_OTEL_EXPORT_ENABLED
  process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = "1"
  process.env.MY_OPENCODE_OTEL_EXPORT_ENABLED = "0"
  try {
    execSync("git init -b main", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: { enabled: true, order: ["primary-worktree-guard"], disabled: [] },
        primaryWorktreeGuard: {
          enabled: true,
          allowedBranches: ["main", "master"],
          blockEdits: true,
          blockBranchSwitches: true,
        },
      },
    })

    const safeCommand = "git status --short --branch"
    const safePayload = { args: { command: safeCommand } }
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-safe" },
      safePayload,
    )
    assert.equal(safePayload.args.command, safeCommand)

    for (const [sessionID, command] of [
      ["session-primary-bash-mutate", "echo hi > file.txt"],
      ["session-primary-command-substitution", 'git status --short --branch "$(touch /tmp/pwn)"'],
    ]) {
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

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "bash", sessionID: "session-primary-chain-switch" },
        { args: { command: "git switch main && git switch feature/foo" } },
      ),
      /Branch switching to 'main' is blocked/,
    )
    const reasonCodes = new Set(
      readAuditEntries(directory)
        .filter((entry) => entry.hook === "primary-worktree-guard")
        .map((entry) => entry.reason_code),
    )
    assert.equal(reasonCodes.has("bash_in_primary_worktree_rerouted"), true)
    assert.equal(reasonCodes.has("branch_switch_in_primary_worktree_blocked"), true)
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

test("primary-worktree-guard allows quoted punctuation in Codememory closeout metadata", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-primary-worktree-"))
  try {
    execSync("git init -b main", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: { enabled: true, order: ["primary-worktree-guard"], disabled: [] },
        primaryWorktreeGuard: {
          enabled: true,
          allowedBranches: ["main", "master"],
          blockEdits: true,
          blockBranchSwitches: true,
        },
      },
    })
    const command =
      "oc end-session --outcome done session_62 --achievements 'validated; closeout & handoff | complete'"
    const payload = { args: { command } }

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-primary-closeout-punctuation" },
      payload,
    )

    assert.equal(payload.args.command, command)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("primary-worktree-guard explains reroute failures when helper path is missing", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-primary-worktree-"))
  const originalHelper = process.env.OPENCODE_MAINTENANCE_HELPER_PATH
  process.env.OPENCODE_MAINTENANCE_HELPER_PATH = join(directory, "missing-helper.py")
  try {
    execSync("git init -b main", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })
    writeFileSync(join(directory, "file.txt"), "v1\n", "utf-8")
    commitAll(directory, "init")

    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: { enabled: true, order: ["primary-worktree-guard"], disabled: [] },
        primaryWorktreeGuard: {
          enabled: true,
          allowedBranches: ["main", "master"],
          blockEdits: true,
          blockBranchSwitches: true,
        },
      },
    })

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "bash", sessionID: "session-primary-helper-missing" },
        { args: { command: "echo hi > file.txt" } }
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
