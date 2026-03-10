import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import GatewayCorePlugin from "../dist/index.js";

function createPlugin(directory) {
  return GatewayCorePlugin({
    directory,
    config: {
      hooks: {
        enabled: true,
        order: ["agent-context-shaper"],
        disabled: [],
      },
    },
  });
}

function seedAgent(directory, name, metadata) {
  const specsDir = join(directory, "agent", "specs");
  mkdirSync(specsDir, { recursive: true });
  writeFileSync(
    join(specsDir, `${name}.json`),
    JSON.stringify({
      name,
      metadata,
      tools: { read: true, glob: true, grep: true },
    }),
    "utf-8",
  );
}

test("agent-context-shaper prepends delegated task focus reminder once", async () => {
  const directory = mkdtempSync(
    join(tmpdir(), "gateway-agent-context-shaper-"),
  );
  try {
    seedAgent(directory, "explore", {
      default_category: "quick",
      triggers: ["map implementation locations"],
      avoid_when: ["scope expands into code changes"],
    });
    const plugin = createPlugin(directory);
    const output = {
      args: {
        subagent_type: "explore",
        category: "quick",
        prompt: "Inspect the codebase and locate orchestration entrypoints.",
      },
    };

    await plugin["tool.execute.before"](
      { tool: "task", sessionID: "session-shaper-1" },
      output,
    );

    const text = String(output.args.prompt);
    assert.match(text, /\[agent-context-shaper\] delegated task focus/);
    assert.match(text, /execute one delegated objective/i);
    assert.match(text, /prioritize: map implementation locations/);

    await plugin["tool.execute.before"](
      { tool: "task", sessionID: "session-shaper-1" },
      output,
    );
    assert.equal(
      (String(output.args.prompt).match(/delegated task focus/g) ?? []).length,
      1,
    );
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

test("agent-context-shaper still shapes trace-only delegations", async () => {
  const directory = mkdtempSync(
    join(tmpdir(), "gateway-agent-context-shaper-"),
  );
  try {
    seedAgent(directory, "explore", {
      default_category: "quick",
    });
    const plugin = createPlugin(directory);
    const output = {
      args: {
        subagent_type: "explore",
        category: "quick",
      },
    };

    await plugin["tool.execute.before"](
      { tool: "task", sessionID: "session-shaper-2" },
      output,
    );

    assert.match(
      String(output.args.prompt ?? ""),
      /\[agent-context-shaper\] delegated task focus/,
    );
    assert.match(String(output.args.prompt ?? ""), /\[DELEGATION TRACE/);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});
