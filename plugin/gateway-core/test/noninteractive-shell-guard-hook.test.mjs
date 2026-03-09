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
    assert.equal(output.args.command.startsWith("CI=true GIT_TERMINAL_PROMPT=0 OPENCODE_SESSION_ID='session-noninteractive-2' MY_OPENCODE_SESSION_ID='session-noninteractive-2' git status"), true)
    assert.equal(output.args.command.includes("npm_config_yes=true"), false)

    const prePrefixed = { args: { command: "CI=true git status" } }
    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-noninteractive-2" },
      prePrefixed,
    )
    assert.equal(prePrefixed.args.command, "GIT_TERMINAL_PROMPT=0 OPENCODE_SESSION_ID='session-noninteractive-2' MY_OPENCODE_SESSION_ID='session-noninteractive-2' CI=true git status")
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
    assert.equal(output.args.command, "OPENCODE_SESSION_ID='session-env-only' MY_OPENCODE_SESSION_ID='session-env-only' python3 script.py")
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
    assert.match(output.args.command, /MY_OPENCODE_SESSION_ID='unsafe '"'"';\$\(whoami\)'/)
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
    assert.match(output.args.command, /^CI=true GIT_TERMINAL_PROMPT=0 OPENCODE_SESSION_ID='unsafe '"'"';\$\(whoami\)' MY_OPENCODE_SESSION_ID='unsafe '"'"';\$\(whoami\)' git status$/)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
