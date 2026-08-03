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

function legacyTaskFocus(trigger, avoid) {
  return [
    "[agent-context-shaper] delegated task focus",
    "- execute one delegated objective for this task call before returning control",
    `- prioritize: ${trigger}`,
    `- avoid: ${avoid}`,
    "- if you uncover extra work, report it as a follow-up instead of expanding scope in the same delegation",
  ].join("\n");
}

function compactTaskFocus(trigger, avoid) {
  return `[agent-context-shaper] delegated task focus: one objective, then return; prioritize: ${trigger}; avoid: ${avoid}; report extras as follow-ups.`;
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
    seedAgent(directory, "reviewer", {
      default_category: "critical",
      triggers: ["final correctness review"],
      avoid_when: ["initial codebase discovery"],
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
    const compact = compactTaskFocus(
      "map implementation locations",
      "scope expands into code changes",
    );
    const legacy = legacyTaskFocus(
      "map implementation locations",
      "scope expands into code changes",
    );
    assert.ok(text.startsWith(`${compact}\n\n`));
    assert.equal(compact.split("\n").length, 1);
    assert.ok(legacy.length - compact.length >= 120);
    assert.match(text, /one objective, then return/i);
    assert.match(text, /prioritize: map implementation locations/);
    assert.match(text, /report extras as follow-ups/);
    assert.ok(text.indexOf("[DELEGATION TRACE") > text.indexOf(compact));
    assert.ok(
      text.indexOf("Inspect the codebase") > text.indexOf("[DELEGATION TRACE"),
    );
    assert.doesNotMatch(text, /- subagent:/);
    assert.doesNotMatch(text, /- category:/);

    await plugin["tool.execute.before"](
      { tool: "task", sessionID: "session-shaper-1" },
      output,
    );
    assert.equal(
      (String(output.args.prompt).match(/delegated task focus/g) ?? []).length,
      1,
    );

    output.args.subagent_type = "reviewer";
    output.args.category = "critical";
    await plugin["tool.execute.before"](
      { tool: "task", sessionID: "session-shaper-1" },
      output,
    );
    const rerouted = String(output.args.prompt);
    assert.equal((rerouted.match(/delegated task focus/g) ?? []).length, 1);
    assert.match(rerouted, /prioritize: final correctness review/);
    assert.match(rerouted, /avoid: initial codebase discovery/);
    assert.match(rerouted, /report extras as follow-ups/);
    assert.doesNotMatch(rerouted, /map implementation locations/);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

test("agent-context-shaper migrates a legacy focus block", async () => {
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
        prompt: `${legacyTaskFocus("old trigger", "old avoid")}\n\nInspect legacy context.`,
      },
    };

    await plugin["tool.execute.before"](
      { tool: "task", sessionID: "session-shaper-legacy" },
      output,
    );

    const text = String(output.args.prompt);
    assert.equal((text.match(/delegated task focus/g) ?? []).length, 1);
    assert.ok(
      text.startsWith(
        compactTaskFocus(
          "map implementation locations",
          "scope expands into code changes",
        ),
      ),
    );
    assert.doesNotMatch(text, /execute one delegated objective/);
    assert.doesNotMatch(text, /old trigger|old avoid/);
    assert.match(text, /Inspect legacy context/);
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

    const text = String(output.args.prompt ?? "");
    assert.ok(
      text.startsWith(
        compactTaskFocus(
          "complete the delegated objective",
          "scope drift or unrelated follow-up work",
        ),
      ),
    );
    assert.match(text, /\[DELEGATION TRACE/);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});
