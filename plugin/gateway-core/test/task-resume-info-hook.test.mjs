import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import GatewayCorePlugin from "../dist/index.js";
import { createTaskResumeInfoHook } from "../dist/hooks/task-resume-info/index.js";

function createPlugin(directory, decisionRuntime) {
  return GatewayCorePlugin({
    directory,
    config: {
      hooks: {
        enabled: true,
        order: ["task-resume-info"],
        disabled: [],
      },
      taskResumeInfo: { enabled: true },
      llmDecisionRuntime: decisionRuntime
        ? {
            enabled: true,
            mode: decisionRuntime.config.mode,
            hookModes: { "task-resume-info": decisionRuntime.config.mode },
            command: "opencode",
            model: "openai/gpt-5.1-codex-mini",
            timeoutMs: 1000,
            maxPromptChars: 200,
            maxContextChars: 200,
            enableCache: true,
            cacheTtlMs: 10000,
            maxCacheEntries: 8,
          }
        : undefined,
    },
    createLlmDecisionRuntime: decisionRuntime ? (() => decisionRuntime) : undefined,
  });
}

function mockDecisionRuntime(char, mode = "assist") {
  return {
    config: { mode },
    async decide(request) {
      return {
        mode,
        accepted: true,
        char,
        raw: char,
        durationMs: 1,
        model: "test-model",
        templateId: request.templateId,
        meaning:
          char === "B"
            ? "continue_and_verify"
            : char === "C"
              ? "continue_only"
              : char === "V"
                ? "verify_only"
                : "none",
      }
    },
  }
}

function readGatewayAuditEvents(directory) {
  return readFileSync(join(directory, ".opencode", "gateway-events.jsonl"), "utf-8")
    .split(/\r?\n/)
    .filter(Boolean)
    .map((line) => JSON.parse(line))
}

test("task-resume-info appends task_id resume hint", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-task-resume-info-"));
  try {
    const plugin = createPlugin(directory);
    const output = { output: "Task completed. task_id: abc-123" };
    await plugin["tool.execute.after"](
      { tool: "task", sessionID: "session-task-1" },
      output,
    );
    assert.match(String(output.output), /Resume hint:/);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

test("task-resume-info appends continuation hint for continue loop marker", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-task-resume-info-"));
  try {
    const plugin = createPlugin(directory);
    const output = { output: "Still pending\n<CONTINUE-LOOP>" };
    await plugin["tool.execute.after"](
      { tool: "task", sessionID: "session-task-2" },
      output,
    );
    assert.match(String(output.output), /Continuation hint:/);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

test("task-resume-info does not duplicate hints already present", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-task-resume-info-"));
  try {
    const plugin = createPlugin(directory);
    const output = {
      output:
        "task_id: abc\nResume hint: keep the returned task_id and reuse it to continue the same subagent session.\n<CONTINUE-LOOP>\nContinuation hint: pending work remains; continue execution directly and avoid asking for extra confirmation turns.",
    };
    await plugin["tool.execute.after"](
      { tool: "task", sessionID: "session-task-3" },
      output,
    );

    const text = String(output.output);
    const resumeCount = (text.match(/Resume hint:/g) ?? []).length;
    const continuationCount = (text.match(/Continuation hint:/g) ?? []).length;
    assert.equal(resumeCount, 1);
    assert.equal(continuationCount, 1);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

test("task-resume-info appends verification hint with subagent session id", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-task-resume-info-"));
  try {
    const plugin = createPlugin(directory);
    const output = { output: "Task finished. Session ID: ses_child123" };
    await plugin["tool.execute.after"](
      { tool: "task", sessionID: "session-task-4" },
      output,
    );
    const text = String(output.output);
    assert.match(text, /Verification hint:/);
    assert.match(text, /\/plan-handoff resume/);
    assert.match(text, /ses_child123/);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

test("task-resume-info appends verification hint with task id fallback", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-task-resume-info-"));
  try {
    const plugin = createPlugin(directory);
    const output = { output: "Task completed. task_id: abc-123" };
    await plugin["tool.execute.after"](
      { tool: "task", sessionID: "session-task-5" },
      output,
    );
    const text = String(output.output);
    assert.match(text, /Verification hint:/);
    assert.match(text, /\/autopilot-resume/);
    assert.match(text, /abc-123/);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

test("task-resume-info uses LLM fallback for ambiguous continuation output", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-task-resume-info-"));
  const previousAudit = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
  process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = "1"
  try {
    const hook = createTaskResumeInfoHook({ enabled: true, decisionRuntime: mockDecisionRuntime("C") });
    const output = { output: "Follow-up cleanup still remains in the same worker thread before final handoff." };
    await hook.event("tool.execute.after", {
      input: { tool: "task", sessionID: "session-task-6" },
      output,
      directory,
    });
    assert.match(String(output.output), /Continuation hint:/);
    const events = readGatewayAuditEvents(directory)
    const recorded = events.find((entry) => entry.reason_code === "llm_task_resume_decision_recorded")
    assert.ok(recorded)
    assert.equal(recorded.session_id, "session-task-6")
    assert.equal(recorded.llm_decision_char, "C")
  } finally {
    if (previousAudit === undefined) {
      delete process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
    } else {
      process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = previousAudit
    }
    rmSync(directory, { recursive: true, force: true });
  }
});

test("task-resume-info uses LLM fallback for ambiguous verification guidance", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-task-resume-info-"));
  const previousAudit = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
  process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = "1"
  try {
    const hook = createTaskResumeInfoHook({ enabled: true, decisionRuntime: mockDecisionRuntime("V") });
    const output = { output: "Keep follow-up fixes attached to worker context ses_child123 until verification is complete." };
    await hook.event("tool.execute.after", {
      input: { tool: "task", sessionID: "session-task-7" },
      output,
      directory,
    });
    const text = String(output.output);
    assert.match(text, /Verification hint:/);
    assert.match(text, /ses_child123/);
    const events = readGatewayAuditEvents(directory)
    const recorded = events.find((entry) => entry.reason_code === "llm_task_resume_decision_recorded")
    assert.ok(recorded)
    assert.equal(recorded.llm_decision_char, "V")
    assert.equal(recorded.resume_target, "ses_child123")
  } finally {
    if (previousAudit === undefined) {
      delete process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
    } else {
      process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = previousAudit
    }
    rmSync(directory, { recursive: true, force: true });
  }
});

test("task-resume-info shadow mode records but does not add semantic hints", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-task-resume-info-"));
  const previousAudit = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
  process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = "1"
  try {
    const hook = createTaskResumeInfoHook({ enabled: true, decisionRuntime: mockDecisionRuntime("C", "shadow") });
    const output = { output: "More follow-up work remains in the same thread." };
    await hook.event("tool.execute.after", {
      input: { tool: "task", sessionID: "session-task-8" },
      output,
      directory,
    });
    assert.doesNotMatch(String(output.output), /Continuation hint:/);
    const events = readGatewayAuditEvents(directory)
    const deferred = events.find((entry) => entry.reason_code === "llm_task_resume_shadow_deferred")
    assert.ok(deferred)
    assert.equal(deferred.llm_decision_char, "C")
  } finally {
    if (previousAudit === undefined) {
      delete process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT
    } else {
      process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = previousAudit
    }
    rmSync(directory, { recursive: true, force: true });
  }
});
