import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import GatewayCorePlugin from "../dist/index.js";
import {
  createAssistantMessageTimestampHook,
  formatAssistantMessageTimestamp,
} from "../dist/hooks/assistant-message-timestamp/index.js";
import { createLlmDecisionRuntime } from "../dist/hooks/shared/llm-decision-runtime.js";

test("assistant-message-timestamp never mutates provider-visible assistant history", async () => {
  const fixtures = [
    {
      output: {
        messages: [
          { info: { role: "assistant" }, parts: [{ type: "text", text: "Earlier answer" }] },
          { info: { role: "user" }, parts: [{ type: "text", text: "Prompt" }] },
          { info: { role: "assistant" }, parts: [{ type: "text", text: "Done shipping the change." }] },
        ],
      },
    },
    {
      output: {
        messages: [
          { info: { role: "assistant" }, parts: [{ type: "tool", text: "Tool metadata" }] },
        ],
      },
    },
  ];
  let nowCalls = 0;
  const hook = createAssistantMessageTimestampHook({
    enabled: true,
    now: () => {
      nowCalls += 1;
      return Date.parse("2026-03-13T12:34:56.000Z");
    },
  });

  for (const payload of fixtures) {
    const before = structuredClone(payload);
    await hook.event("experimental.chat.messages.transform", payload);
    assert.deepEqual(payload, before);
  }

  assert.equal(nowCalls, 0);
  assert.deepEqual(hook.events, [
    "experimental.text.complete",
    "message.updated",
    "message.part.updated",
    "message.part.delta",
    "session.idle",
    "session.deleted",
  ]);
});

test("assistant-message-timestamp samples no clock for disabled, deleted, or unsupported events", async () => {
  let nowCalls = 0;
  const now = () => {
    nowCalls += 1;
    return Date.parse("2026-03-13T12:34:56.000Z");
  };
  const enabledHook = createAssistantMessageTimestampHook({ enabled: true, now });
  const disabledHook = createAssistantMessageTimestampHook({ enabled: false, now });

  await disabledHook.event("experimental.text.complete", { output: { text: "Unchanged." } });
  await enabledHook.event("experimental.chat.system.transform", { output: { system: [] } });
  await enabledHook.event("session.deleted", {});

  assert.equal(nowCalls, 0);
});

test("assistant-message-timestamp prepends timestamp to experimental.text.complete output", async () => {
  const timestamp = Date.parse("2026-03-13T12:34:56.000Z");
  const hook = createAssistantMessageTimestampHook({ enabled: true, now: () => timestamp });
  const payload = {
    output: {
      text: "Honey never spoils.",
    },
  };

  await hook.event("experimental.text.complete", payload);

  assert.equal(
    payload.output.text,
    `${formatAssistantMessageTimestamp(timestamp)}\nHoney never spoils.`,
  );
});

test("assistant-message-timestamp uses zero-padded sortable dates", () => {
  const timestamp = new Date(2026, 2, 3, 4, 5, 6).getTime();
  assert.equal(formatAssistantMessageTimestamp(timestamp), "[2026-03-03 04:05:06]");
});

test("assistant-message-timestamp keeps session.idle fallback behavior", async () => {
  const timestamp = Date.parse("2026-03-13T12:34:56.000Z");
  const hook = createAssistantMessageTimestampHook({ enabled: true, now: () => timestamp });
  const payload = { output: { output: "Done shipping the change." } };

  await hook.event("session.idle", payload);

  assert.equal(
    payload.output.output,
    `${formatAssistantMessageTimestamp(timestamp)}\nDone shipping the change.`,
  );
});

test("assistant-message-timestamp preserves all assistant lifecycle decoration paths", async () => {
  const timestamp = Date.parse("2026-03-13T12:34:56.000Z");
  const expectedPrefix = formatAssistantMessageTimestamp(timestamp);

  const updatedHook = createAssistantMessageTimestampHook({ enabled: true, now: () => timestamp });
  const updatedPayload = {
    properties: {
      info: { role: "assistant", id: "message-updated" },
      parts: [{ type: "text", text: "Complete message." }],
    },
  };
  await updatedHook.event("message.updated", updatedPayload);
  assert.equal(updatedPayload.properties.parts[0].text, `${expectedPrefix}\nComplete message.`);

  const partHook = createAssistantMessageTimestampHook({ enabled: true, now: () => timestamp });
  await partHook.event("message.updated", {
    properties: { info: { role: "assistant", id: "message-part" } },
  });
  const partPayload = {
    properties: {
      messageID: "message-part",
      partID: "part-1",
      part: { type: "text", text: "Part update." },
    },
  };
  await partHook.event("message.part.updated", partPayload);
  await partHook.event("message.part.updated", partPayload);
  assert.equal(partPayload.properties.part.text, `${expectedPrefix}\nPart update.`);

  const deltaHook = createAssistantMessageTimestampHook({ enabled: true, now: () => timestamp });
  await deltaHook.event("message.updated", {
    properties: { info: { role: "assistant", id: "message-delta" } },
  });
  const deltaPayload = {
    properties: {
      messageID: "message-delta",
      partID: "part-2",
      delta: "Streaming delta.",
    },
  };
  await deltaHook.event("message.part.delta", deltaPayload);
  await deltaHook.event("message.part.delta", deltaPayload);
  assert.equal(deltaPayload.properties.delta, `${expectedPrefix}\nStreaming delta.`);
});

test("assistant-message-timestamp prepends queued LLM fallback notice once on session.idle", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-assistant-timestamp-"));
  const timestamp = Date.parse("2026-03-13T12:34:56.000Z");
  const hook = createAssistantMessageTimestampHook({ enabled: true, now: () => timestamp });
  const runtime = createLlmDecisionRuntime({
    directory,
    config: {
      enabled: true,
      mode: "assist",
      command: "opencode",
      model: "github-copilot/gpt-5-mini",
      timeoutMs: 1000,
      failureCooldownMs: 120000,
      maxPromptChars: 200,
      maxContextChars: 200,
      enableCache: false,
      cacheTtlMs: 10000,
      maxCacheEntries: 8,
    },
    runner: async () => {
      throw new Error("provider unavailable");
    },
  });
  await runtime.decide({
    hookId: "test-hook",
    sessionId: "session-notice-1",
    templateId: "notice-v1",
    instruction: "Classify this request.",
    context: "Example context.",
    allowedChars: ["Y", "N"],
  });
  const historyPayload = {
    output: {
      messages: [
        { info: { role: "assistant" }, parts: [{ type: "text", text: "Stored reply." }] },
      ],
    },
  };
  const historyBefore = structuredClone(historyPayload);
  await hook.event("experimental.chat.messages.transform", historyPayload);
  assert.deepEqual(historyPayload, historyBefore);
  const payload = {
    directory,
    properties: { sessionID: "session-notice-1" },
    output: { output: "Done shipping the change." },
  };

  await hook.event("session.idle", payload);

  assert.match(payload.output.output, /^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]\n\[llm-decision-runtime\] LLM helper unavailable;/);
  assert.match(payload.output.output, /Done shipping the change\./);

  const nextPayload = {
    directory,
    properties: { sessionID: "session-notice-1" },
    output: { output: "Second reply." },
  };
  await hook.event("session.idle", nextPayload);
  assert.doesNotMatch(nextPayload.output.output, /\[llm-decision-runtime\]/);

  rmSync(directory, { recursive: true, force: true });
});

test("assistant-message-timestamp skips second- and minute-precision prefixed output without sampling the clock", async () => {
  const timestamp = Date.parse("2026-03-13T12:34:56.000Z");
  let nowCalls = 0;
  const hook = createAssistantMessageTimestampHook({
    enabled: true,
    now: () => {
      nowCalls += 1;
      return timestamp;
    },
  });
  const existing = formatAssistantMessageTimestamp(timestamp);
  const payloads = [
    { output: { text: `${existing}\nStill here.` } },
    { output: { text: "[2026-03-13 12:34]\nStill here." } },
  ];

  for (const payload of payloads) {
    const before = structuredClone(payload);
    await hook.event("experimental.text.complete", payload);
    assert.deepEqual(payload, before);
  }

  assert.equal(nowCalls, 0);
});

test("assistant-message-timestamp still stamps bracket-leading non-prefixed output", async () => {
  const timestamp = Date.parse("2026-03-13T12:34:56.000Z");
  const hook = createAssistantMessageTimestampHook({ enabled: true, now: () => timestamp });
  const payload = {
    output: {
      text: "[note] keep this visible.",
    },
  };

  await hook.event("experimental.text.complete", payload);

  assert.equal(payload.output.text, `${formatAssistantMessageTimestamp(timestamp)}\n[note] keep this visible.`);
});

test("gateway-core dispatches experimental.text.complete to the timestamp hook", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-assistant-timestamp-"));
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["assistant-message-timestamp"],
          disabled: [],
        },
        assistantMessageTimestamp: { enabled: true },
      },
    });
    const output = { text: "Octopuses have three hearts." };

    await plugin["experimental.text.complete"](
      { sessionID: "s1", messageID: "m1", partID: "p1" },
      output,
    );

    assert.match(
      output.text,
      /^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]\nOctopuses have three hearts\.$/,
    );
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});
