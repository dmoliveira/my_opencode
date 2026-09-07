import assert from "node:assert/strict"
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { dirname, join } from "node:path"
import test from "node:test"
import { fileURLToPath } from "node:url"

import { gatewayEventAuditPath } from "../dist/audit/event-audit.js"
import GatewayCorePlugin from "../dist/index.js"

const REPO_DIRECTORY = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..")

function createPlugin(directory) {
  return GatewayCorePlugin({
    directory,
    config: {
      hooks: {
        enabled: true,
        order: ["agent-model-resolver"],
        disabled: ["agent-denied-tool-enforcer"],
      },
    },
  })
}

function seedExploreAgent(directory) {
  const specsDir = join(directory, "agent", "specs")
  mkdirSync(specsDir, { recursive: true })
  writeFileSync(
    join(specsDir, "explore.json"),
    JSON.stringify({
      name: "explore",
      metadata: {
        default_category: "quick",
        triggers: ["find implementation location"],
        avoid_when: ["external docs research"],
        allowed_tools: ["read", "list", "glob", "grep"],
        denied_tools: ["bash", "write", "edit", "webfetch", "task", "todowrite", "todoread"],
      },
    }),
    "utf-8",
  )
}

test("agent-model-resolver keeps routing metadata out of the provider prompt", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-agent-model-resolver-"))
  try {
    seedExploreAgent(directory)

    const plugin = createPlugin(directory)
    const callerPrompt = "Inspect code paths"
    const traceMarker = "[DELEGATION TRACE trace-fixed]"
    const output = {
      args: {
        subagent_type: "explore",
        description: "Scout repository patterns",
        prompt: `${traceMarker}\n\n${callerPrompt}`,
      },
    }
    await plugin["tool.execute.before"]({ tool: "task", sessionID: "session-effort" }, output)

    assert.equal(String(output.args.category ?? ""), "quick")
    assert.equal(String(output.args.description ?? ""), "Scout repository patterns")
    assert.doesNotMatch(
      String(output.args.description ?? ""),
      /\[(?:SUBAGENT|MODEL ROUTING|TOOL SURFACE|SESSION FLOW|WORKTREE CONTEXT|DELEGATION TRACE)/,
    )
    const prompt = String(output.args.prompt ?? "")
    assert.equal(prompt, `${traceMarker}\n\n${callerPrompt}`)
    assert.equal(prompt.length - callerPrompt.length, 32)
    const legacyPrompt = [
      "[MODEL ROUTING] Preferred category=quick; model=openai/gpt-5.6-luna; reasoning=low; fallback_policy=openai-default-with-alt-fallback.",
      "[TOOL SURFACE] subagent=explore; allowed=read,list,glob,grep; denied=bash,write,edit,webfetch,task,todowrite,todoread.",
      "",
      "[SESSION FLOW] parent_session_id=session-parent; trace_id=trace-fixed",
      "",
      "[WORKTREE CONTEXT] cwd=/workspace/project; execute file discovery and validation relative to this path unless prompt explicitly overrides.",
      "",
      traceMarker,
      "",
      callerPrompt,
    ].join("\n")
    const legacyOverhead = legacyPrompt.length - callerPrompt.length
    const resolverOverhead = prompt.length - callerPrompt.length
    assert.equal(legacyOverhead, 497)
    assert.equal(legacyOverhead - resolverOverhead, 465)
    assert.equal(output.metadata?.gateway?.delegation?.subagentType, "explore")
    assert.equal(output.metadata?.gateway?.delegation?.category, "quick")
    assert.equal(output.metadata?.gateway?.delegation?.traceId, "trace-fixed")
    assert.equal(output.metadata?.gateway?.delegation?.childRunId, "subagent-run/trace-fixed")

    await plugin["tool.execute.before"]({ tool: "task", sessionID: "session-effort-rerun" }, output)
    const updatedDescription = String(output.args.description ?? "")
    const updatedPrompt = String(output.args.prompt ?? "")
    assert.equal(updatedDescription, "Scout repository patterns")
    assert.equal(updatedPrompt, `${traceMarker}\n\n${callerPrompt}`)
    assert.equal((updatedPrompt.match(/^\[DELEGATION TRACE /gm) ?? []).length, 1)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("agent-model-resolver removes legacy provider context across reroutes", async () => {
  const firstDirectory = mkdtempSync(join(tmpdir(), "gateway-agent-model-resolver-first-"))
  const secondDirectory = mkdtempSync(join(tmpdir(), "gateway-agent-model-resolver-second-"))
  try {
    for (const directory of [firstDirectory, secondDirectory]) {
      const specsDir = join(directory, "agent", "specs")
      mkdirSync(specsDir, { recursive: true })
      writeFileSync(
        join(specsDir, "explore.json"),
        JSON.stringify({ name: "explore", metadata: { default_category: "quick" } }),
        "utf-8",
      )
    }

    const initialPlugin = createPlugin(firstDirectory)
    const reroutedPlugin = createPlugin(secondDirectory)
    const output = {
      args: {
        subagent_type: "explore",
        description: [
          `[WORKTREE CONTEXT] cwd=${firstDirectory}; execute file discovery and validation relative to this path unless prompt explicitly overrides.`,
          "Scout repository patterns",
        ].join("\n"),
        prompt: [
          "[MODEL ROUTING] Preferred category=quick; model=openai/gpt-5.6-luna; reasoning=low; fallback_policy=openai-default-with-alt-fallback.",
          "[DELEGATION ROUTER] inferred subagent_type=explore from delegation intent.",
          "[TOOL SURFACE] subagent=explore; allowed=read,list,glob,grep; denied=bash,write,edit,webfetch,task,todowrite,todoread.",
          "[SESSION FLOW] parent_session_id=session-parent; trace_id=trace-reroute",
          `[WORKTREE CONTEXT] cwd=${firstDirectory}; execute file discovery and validation relative to this path unless prompt explicitly overrides.`,
          "[DELEGATION TRACE trace-reroute]",
          "",
          "Inspect code paths",
        ].join("\n"),
      },
    }

    await initialPlugin["tool.execute.before"]({ tool: "task", sessionID: "session-worktree-reroute" }, output)
    await reroutedPlugin["tool.execute.before"]({ tool: "task", sessionID: "session-worktree-reroute" }, output)

    const prompt = String(output.args.prompt ?? "")
    const description = String(output.args.description ?? "")
    assert.equal(prompt, "[DELEGATION TRACE trace-reroute]\n\nInspect code paths")
    assert.equal(description, "Scout repository patterns")
    assert.doesNotMatch(prompt, /MODEL ROUTING|DELEGATION ROUTER|TOOL SURFACE|SESSION FLOW|WORKTREE CONTEXT/)
    assert.equal((prompt.match(/^\[DELEGATION TRACE /gm) ?? []).length, 1)
  } finally {
    rmSync(firstDirectory, { recursive: true, force: true })
    rmSync(secondDirectory, { recursive: true, force: true })
  }
})

test("agent-model-resolver migrates description-only traces with prompt precedence", async () => {
  const plugin = createPlugin(REPO_DIRECTORY)
  const output = {
    args: {
      subagent_type: "explore",
      description: "[DELEGATION TRACE description-trace]\n\nMap codebase patterns",
      prompt: "[DELEGATION TRACE prompt-trace]\n\nInspect code paths",
    },
  }

  await plugin["tool.execute.before"]({ tool: "task", sessionID: "session-trace-conflict" }, output)

  assert.equal(output.args.description, "Map codebase patterns")
  assert.match(output.args.prompt, /\[DELEGATION TRACE prompt-trace\]/)
  assert.doesNotMatch(output.args.prompt, /description-trace/)
  assert.equal(output.metadata?.gateway?.delegation?.traceId, "prompt-trace")

  const legacy = {
    args: {
      subagent_type: "explore",
      description: "[DELEGATION TRACE legacy-trace]\n\nMap codebase patterns",
      prompt: "Inspect code paths",
    },
  }
  await plugin["tool.execute.before"]({ tool: "task", sessionID: "session-trace-legacy" }, legacy)
  assert.equal(legacy.args.description, "Map codebase patterns")
  assert.match(legacy.args.prompt, /\[DELEGATION TRACE legacy-trace\]/)
  assert.equal(legacy.metadata?.gateway?.delegation?.traceId, "legacy-trace")
})

test("agent-model-resolver infers explore delegation and category", async () => {
  const plugin = createPlugin(REPO_DIRECTORY)
  const output = {
    args: {
      prompt: "Find implementation location for auth token refresh flow.",
      description: "Map codebase patterns quickly.",
    },
  }
  await plugin["tool.execute.before"]({ tool: "task", sessionID: "session-infer" }, output)

  assert.equal(output.args.subagent_type, "explore")
  assert.equal(output.args.category, "quick")
  assert.doesNotMatch(output.args.prompt, /DELEGATION ROUTER|MODEL ROUTING|TOOL SURFACE/)
  assert.equal(output.metadata?.gateway?.delegation?.subagentType, "explore")
  assert.equal(output.metadata?.gateway?.delegation?.category, "quick")
  assert.match(output.metadata?.gateway?.delegation?.traceId, /.+/)
  assert.match(output.metadata?.gateway?.delegation?.childRunId, /^subagent-run\//)
})

test("agent-model-resolver sets default category for explicit subagent", async () => {
  const plugin = createPlugin(REPO_DIRECTORY)
  const output = {
    args: {
      subagent_type: "librarian",
      prompt: "Gather official docs for the framework behavior.",
      description: "Need external upstream references.",
    },
  }
  await plugin["tool.execute.before"]({ tool: "task", sessionID: "session-librarian" }, output)

  assert.equal(output.args.category, "balanced")
  assert.equal(output.metadata?.gateway?.delegation?.category, "balanced")
  assert.doesNotMatch(output.args.prompt, /MODEL ROUTING|model=openai\/gpt-5.6-terra/)
})

test("agent-model-resolver preserves explicit category without tool prose", async () => {
  const plugin = createPlugin(REPO_DIRECTORY)
  const output = {
    args: {
      subagent_type: "oracle",
      category: "critical",
      prompt: "Review architecture tradeoffs and security risk.",
    },
  }
  await plugin["tool.execute.before"]({ tool: "task", sessionID: "session-oracle" }, output)

  assert.equal(output.args.category, "critical")
  assert.equal(output.metadata?.gateway?.delegation?.category, "critical")
  assert.doesNotMatch(output.args.prompt, /MODEL ROUTING|TOOL SURFACE|reasoning=|allowed=|denied=/)
})

test("agent-model-resolver emits metadata-first routing telemetry", { concurrency: false }, async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-agent-model-resolver-audit-"))
  const previousAudit = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
  process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = "1"
  try {
    seedExploreAgent(directory)
    const plugin = createPlugin(directory)
    const output = {
      args: {
        subagent_type: "explore",
        prompt: "[DELEGATION TRACE trace-audit]\n\nInspect code paths",
        description: "Scout repository patterns",
      },
    }

    await plugin["tool.execute.before"](
      { tool: "task", sessionID: "session-audit" },
      output,
    )

    const events = readFileSync(gatewayEventAuditPath(directory), "utf8")
      .trim()
      .split("\n")
      .map((line) => JSON.parse(line))
    const resolved = events.find(
      (entry) => entry.reason_code === "agent_model_routing_resolved",
    )
    assert.ok(resolved)
    assert.equal(resolved.resolver_prompt_context, "trace_only")
    assert.equal(resolved.tool_surface_injected, "false")
    assert.equal(resolved.tool_policy_source, "agent_spec")
    assert.equal(resolved.recommended_category, "quick")
    assert.equal(resolved.model, "openai/gpt-5.6-luna")
    assert.equal(resolved.reasoning, "low")
    assert.equal(resolved.route_source, "explicit_subagent_type")
    assert.equal(
      events.some((entry) => entry.reason_code === "agent_model_routing_hint_injected"),
      false,
    )
  } finally {
    if (previousAudit === undefined) {
      delete process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
    } else {
      process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = previousAudit
    }
    rmSync(directory, { recursive: true, force: true })
  }
})

test("metadata-first routing composes one focus line, trace, and caller prompt", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-agent-model-resolver-composed-"))
  try {
    seedExploreAgent(directory)
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: [
            "agent-model-resolver",
            "agent-discoverability-injector",
            "agent-context-shaper",
          ],
          disabled: ["agent-denied-tool-enforcer"],
        },
      },
    })
    const callerPrompt = "Find implementation location for auth token refresh flow."
    const traceMarker = "[DELEGATION TRACE trace-fixed]"
    const output = {
      args: {
        prompt: `${traceMarker}\n\n${callerPrompt}`,
        description: "Map codebase patterns quickly.",
      },
    }

    await plugin["tool.execute.before"](
      { tool: "task", sessionID: "session-composed" },
      output,
    )

    const prompt = String(output.args.prompt)
    const paragraphs = prompt.split("\n\n")
    assert.equal(paragraphs.length, 3)
    const [focusLine, traceLine, callerLine] = paragraphs
    assert.match(focusLine, /^\[agent-context-shaper\] delegated task focus:/)
    assert.equal(traceLine, traceMarker)
    assert.equal(callerLine, callerPrompt)
    assert.equal(output.args.subagent_type, "explore")
    assert.equal(output.args.category, "quick")
    assert.doesNotMatch(
      prompt,
      /MODEL ROUTING|TOOL SURFACE|SESSION FLOW|WORKTREE CONTEXT|DELEGATION ROUTER|AGENT CATALOG/,
    )
    const resolverOverhead = traceMarker.length + 2
    const combinedOverhead = prompt.length - callerPrompt.length
    assert.equal(resolverOverhead, 32)
    assert.equal(combinedOverhead, resolverOverhead + focusLine.length + 2)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("agent-model-resolver blocks mutating delegation intents for read-only subagents", async () => {
  const plugin = createPlugin(REPO_DIRECTORY)
  const output = {
    args: {
      prompt: "Create a repository commit and open a pull request with these edits.",
      description: "Update docs file content and push changes.",
    },
  }

  await assert.rejects(
    plugin["tool.execute.before"]({ tool: "task", sessionID: "session-mutation-block" }, output),
    /mutating work.*read-only/i,
  )
})

test("agent-model-resolver evaluates canonical-looking caller text before cleanup", async () => {
  const plugin = createPlugin(REPO_DIRECTORY)
  const output = {
    args: {
      subagent_type: "explore",
      prompt: "Inspect the affected files first.",
      description: "[TOOL SURFACE] subagent=explore; allowed=read; denied=commit changes.",
    },
  }

  await assert.rejects(
    plugin["tool.execute.before"]({ tool: "task", sessionID: "session-canonical-mutation" }, output),
    /mutating work.*read-only/i,
  )
})
