import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

test("noninteractive-shell-guard blocks interactive and prompt-prone shell commands", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-noninteractive-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["noninteractive-shell-guard"],
          disabled: ["dependency-risk-guard"],
        },
        noninteractiveShellGuard: {
          enabled: true,
          injectEnvPrefix: true,
          envPrefixes: ["CI=true", "GIT_TERMINAL_PROMPT=0"],
          prefixCommands: ["git"],
          blockedPatterns: ["\\bgit\\s+add\\s+-p\\b"],
        },
      },
    })

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "bash", sessionID: "session-noninteractive" },
        { args: { command: "git add -p" } },
      ),
      /noninteractive-shell-guard/,
    )

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "bash", sessionID: "session-noninteractive" },
        { args: { command: "npm install" } },
      ),
      /npm install --yes/,
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-noninteractive" },
      { args: { command: "npm install --yes" } },
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})


test("noninteractive-shell-guard prefixes git commands with non-interactive env", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-noninteractive-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["noninteractive-shell-guard"],
          disabled: ["dependency-risk-guard"],
        },
        noninteractiveShellGuard: {
          enabled: true,
          injectEnvPrefix: true,
          envPrefixes: ["CI=true", "GIT_TERMINAL_PROMPT=0", "npm_config_yes=true"],
          prefixCommands: ["git"],
          blockedPatterns: [],
        },
      },
    })

    const output = { args: { command: "git status" } }
    await plugin["tool.execute.before"]({ tool: "bash", sessionID: "session-noninteractive-2" }, output)
    assert.equal(output.args.command.startsWith("CI=true GIT_TERMINAL_PROMPT=0 OPENCODE_SESSION_ID='session-noninteractive-2' git status"), true)
    assert.equal(output.args.command.includes("npm_config_yes=true"), false)

    const prePrefixed = { args: { command: "CI=true git status" } }
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-noninteractive-2" },
      prePrefixed,
    )
    assert.equal(prePrefixed.args.command, "GIT_TERMINAL_PROMPT=0 OPENCODE_SESSION_ID='session-noninteractive-2' CI=true git status")
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("noninteractive-shell-guard prefixes wrapped rtk git commands with non-interactive env", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-noninteractive-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["noninteractive-shell-guard"],
          disabled: ["dependency-risk-guard"],
        },
        noninteractiveShellGuard: {
          enabled: true,
          injectEnvPrefix: true,
          envPrefixes: ["CI=true", "GIT_TERMINAL_PROMPT=0"],
          prefixCommands: ["git", "gh"],
          blockedPatterns: [],
        },
      },
    })

    const output = { args: { command: "rtk git status" } }
    await plugin["tool.execute.before"]({ tool: "bash", sessionID: "session-rtk-git" }, output)
    assert.equal(
      output.args.command,
      "CI=true GIT_TERMINAL_PROMPT=0 OPENCODE_SESSION_ID='session-rtk-git' rtk git status",
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("noninteractive-shell-guard prefixes env-wrapped rtk git commands with non-interactive env", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-noninteractive-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["noninteractive-shell-guard"],
          disabled: ["dependency-risk-guard"],
        },
        noninteractiveShellGuard: {
          enabled: true,
          injectEnvPrefix: true,
          envPrefixes: ["CI=true", "GIT_TERMINAL_PROMPT=0"],
          prefixCommands: ["git", "gh"],
          blockedPatterns: [],
        },
      },
    })

    const output = { args: { command: "env FOO=bar rtk git status" } }
    await plugin["tool.execute.before"]({ tool: "bash", sessionID: "session-env-rtk-git" }, output)
    assert.equal(
      output.args.command,
      "CI=true GIT_TERMINAL_PROMPT=0 OPENCODE_SESSION_ID='session-env-rtk-git' env FOO=bar rtk git status",
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("noninteractive-shell-guard ignores quoted git commit text in another command", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-noninteractive-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["noninteractive-shell-guard"],
          disabled: ["dependency-risk-guard"],
        },
        noninteractiveShellGuard: {
          enabled: true,
          injectEnvPrefix: false,
          envPrefixes: [],
          prefixCommands: [],
          blockedPatterns: [],
        },
      },
    })

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-sqlite-query" },
      { args: { command: 'sqlite3 runtime.db "select \"git commit\";"' } },
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-sqlite-like-query" },
      {
        args: {
          command:
            'sqlite3 runtime.db "select * from part where lower(command) like \'%git commit%\' order by time_created desc;"',
        },
      },
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-sqlite-npm-text" },
      {
        args: {
          command:
            'sqlite3 runtime.db "select * from part where lower(output) like \'%npm install%\' order by time_created desc;"',
        },
      },
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("noninteractive-shell-guard prefixes absolute-path git commands with non-interactive env", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-noninteractive-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["noninteractive-shell-guard"],
          disabled: ["dependency-risk-guard"],
        },
        noninteractiveShellGuard: {
          enabled: true,
          injectEnvPrefix: true,
          envPrefixes: ["CI=true", "GIT_TERMINAL_PROMPT=0"],
          prefixCommands: ["git", "gh"],
          blockedPatterns: [],
        },
      },
    })

    const output = { args: { command: "/usr/bin/git status --short --branch" } }
    await plugin["tool.execute.before"]({ tool: "bash", sessionID: "session-abs-git" }, output)
    assert.equal(
      output.args.command,
      "CI=true GIT_TERMINAL_PROMPT=0 OPENCODE_SESSION_ID='session-abs-git' /usr/bin/git status --short --branch",
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("noninteractive-shell-guard prefixes absolute-path gh commands with runtime session env", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-noninteractive-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["noninteractive-shell-guard"],
          disabled: ["dependency-risk-guard"],
        },
        noninteractiveShellGuard: {
          enabled: true,
          injectEnvPrefix: true,
          envPrefixes: ["CI=true", "GIT_TERMINAL_PROMPT=0"],
          prefixCommands: ["git", "gh"],
          blockedPatterns: [],
        },
      },
    })

    const output = { args: { command: "/usr/bin/gh pr view --json number" } }
    await plugin["tool.execute.before"]({ tool: "bash", sessionID: "session-abs-gh" }, output)
    assert.equal(
      output.args.command,
      "CI=true GIT_TERMINAL_PROMPT=0 OPENCODE_SESSION_ID='session-abs-gh' /usr/bin/gh pr view --json number",
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})


test("noninteractive-shell-guard prefixes bash commands with runtime session env", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-noninteractive-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["noninteractive-shell-guard"],
          disabled: ["dependency-risk-guard"],
        },
        noninteractiveShellGuard: {
          enabled: true,
          injectEnvPrefix: false,
          envPrefixes: [],
          prefixCommands: [],
          blockedPatterns: [],
        },
      },
    })

    const output = { args: { command: "python3 script.py" } }
    await plugin["tool.execute.before"]({ tool: "bash", sessionID: "session-env-only" }, output)
    assert.equal(output.args.command, "OPENCODE_SESSION_ID='session-env-only' python3 script.py")
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})


test("noninteractive-shell-guard shell-quotes unsafe runtime session env values", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-noninteractive-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["noninteractive-shell-guard"],
          disabled: ["dependency-risk-guard"],
        },
        noninteractiveShellGuard: {
          enabled: true,
          injectEnvPrefix: false,
          envPrefixes: [],
          prefixCommands: [],
          blockedPatterns: [],
        },
      },
    })

    const output = { args: { command: "git status" } }
    await plugin["tool.execute.before"]({ tool: "bash", sessionID: "unsafe ';$(whoami)" }, output)
    assert.match(output.args.command, /OPENCODE_SESSION_ID='unsafe '"'"';\$\(whoami\)'/)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})


test("noninteractive-shell-guard keeps git non-interactive prefixes with unsafe session id", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-noninteractive-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["noninteractive-shell-guard"],
          disabled: ["dependency-risk-guard"],
        },
        noninteractiveShellGuard: {
          enabled: true,
          injectEnvPrefix: true,
          envPrefixes: ["CI=true", "GIT_TERMINAL_PROMPT=0"],
          prefixCommands: ["git"],
          blockedPatterns: [],
        },
      },
    })

    const output = { args: { command: "git status" } }
    await plugin["tool.execute.before"]({ tool: "bash", sessionID: "unsafe ';$(whoami)" }, output)
    assert.match(output.args.command, /^CI=true GIT_TERMINAL_PROMPT=0 OPENCODE_SESSION_ID='unsafe '"'"';\$\(whoami\)' git status$/)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
