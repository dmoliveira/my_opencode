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
          envPrefixes: ["CI=true", "GIT_TERMINAL_PROMPT=0", "GH_PROMPT_DISABLED=1"],
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
      /git add <path>|git add \\./,
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

test("noninteractive-shell-guard includes editor remediation for interactive commands", async () => {
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
          blockedPatterns: ["\\bvim\\b"],
        },
      },
    })

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "bash", sessionID: "session-editor-blocked" },
        { args: { command: "vim README.md" } },
      ),
      /file-edit tools or scripted file writes/i,
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("noninteractive-shell-guard includes gh pr create remediation for browser/editor flows", async () => {
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

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "bash", sessionID: "session-gh-create-web" },
        { args: { command: "gh pr create --web" } },
      ),
      /--title|--body-file|--fill-verbose/i,
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("noninteractive-shell-guard includes git commit remediation without -m", async () => {
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

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "bash", sessionID: "session-git-commit-blocked" },
        { args: { command: "git commit" } },
      ),
      /git commit -m/i,
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
          envPrefixes: ["CI=true", "GIT_TERMINAL_PROMPT=0", "GH_PROMPT_DISABLED=1"],
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
          envPrefixes: ["CI=true", "GIT_TERMINAL_PROMPT=0", "GH_PROMPT_DISABLED=1"],
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
          envPrefixes: ["CI=true", "GIT_TERMINAL_PROMPT=0", "GH_PROMPT_DISABLED=1"],
          prefixCommands: ["git", "gh"],
          blockedPatterns: [],
        },
      },
    })

    const output = { args: { command: "/usr/bin/gh pr view --json number" } }
    await plugin["tool.execute.before"]({ tool: "bash", sessionID: "session-abs-gh" }, output)
    assert.equal(
      output.args.command,
      "CI=true GIT_TERMINAL_PROMPT=0 GH_PROMPT_DISABLED=1 OPENCODE_SESSION_ID='session-abs-gh' /usr/bin/gh pr view --json number",
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("noninteractive-shell-guard prefixes scripted gh pr create with noninteractive env", async () => {
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
          envPrefixes: ["CI=true", "GIT_TERMINAL_PROMPT=0", "GH_PROMPT_DISABLED=1"],
          prefixCommands: ["git", "gh"],
          blockedPatterns: [],
        },
      },
    })

    const output = { args: { command: 'gh pr create --title "Fix" --body "Validation complete" --base main --head feature' } }
    await plugin["tool.execute.before"]({ tool: "bash", sessionID: "session-gh-pr-create" }, output)
    assert.equal(
      output.args.command,
      "CI=true GIT_TERMINAL_PROMPT=0 GH_PROMPT_DISABLED=1 OPENCODE_SESSION_ID='session-gh-pr-create' gh pr create --title \"Fix\" --body \"Validation complete\" --base main --head feature",
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("noninteractive-shell-guard blocks underspecified gh pr create in headless mode", async () => {
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
          envPrefixes: ["CI=true", "GIT_TERMINAL_PROMPT=0", "GH_PROMPT_DISABLED=1"],
          prefixCommands: ["git", "gh"],
          blockedPatterns: [],
        },
      },
    })

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "bash", sessionID: "session-gh-pr-create-bad" },
        { args: { command: "gh pr create --base main --head feature" } },
      ),
      /Use non-interactive gh PR creation format/,
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("noninteractive-shell-guard allows noninteractive gh api PR creation and curl PR creation", async () => {
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
          envPrefixes: ["CI=true", "GIT_TERMINAL_PROMPT=0", "GH_PROMPT_DISABLED=1"],
          prefixCommands: ["git", "gh"],
          blockedPatterns: [],
        },
      },
    })

    const ghApi = { args: { command: "gh api repos/foo/bar/pulls -X POST -f title=Fix -f head=feature -f base=main -f body=Ready" } }
    await plugin["tool.execute.before"]({ tool: "bash", sessionID: "session-gh-api-pr-create" }, ghApi)
    assert.equal(
      ghApi.args.command,
      "CI=true GIT_TERMINAL_PROMPT=0 GH_PROMPT_DISABLED=1 OPENCODE_SESSION_ID='session-gh-api-pr-create' gh api repos/foo/bar/pulls -X POST -f title=Fix -f head=feature -f base=main -f body=Ready",
    )

    const curlApi = { args: { command: "curl -fsSL -X POST https://api.github.com/repos/foo/bar/pulls -H 'Authorization: Bearer token' -H 'Accept: application/vnd.github+json' -d '{\"title\":\"Fix\",\"head\":\"feature\",\"base\":\"main\"}'" } }
    await plugin["tool.execute.before"]({ tool: "bash", sessionID: "session-curl-pr-create" }, curlApi)
    assert.equal(
      curlApi.args.command,
      "OPENCODE_SESSION_ID='session-curl-pr-create' curl -fsSL -X POST https://api.github.com/repos/foo/bar/pulls -H 'Authorization: Bearer token' -H 'Accept: application/vnd.github+json' -d '{\"title\":\"Fix\",\"head\":\"feature\",\"base\":\"main\"}'",
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
