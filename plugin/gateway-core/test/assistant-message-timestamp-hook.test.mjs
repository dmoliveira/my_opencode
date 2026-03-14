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

test("assistant-message-timestamp prepends a one-line sortable local timestamp to the latest assistant transform message", async () => {
  const timestamp = Date.parse("2026-03-13T12:34:56.000Z");
  const hook = createAssistantMessageTimestampHook({
    enabled: true,
    now: () => timestamp,
  });
  const payload = {
    output: {
      messages: [
        { info: { role: "assistant" }, parts: [{ type: "text", text: "Earlier answer" }] },
        { info: { role: "user" }, parts: [{ type: "text", text: "Prompt" }] },
        { info: { role: "assistant" }, parts: [{ type: "text", text: "Done shipping the change." }] },
      ],
    },
  };

  await hook.event("experimental.chat.messages.transform", payload);

  assert.equal(
    payload.output.messages[2].parts[0].text,
    `${formatAssistantMessageTimestamp(timestamp)}\nDone shipping the change.`,
  );
  assert.equal(payload.output.messages[0].parts[0].text, "Earlier answer");
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
      model: "github-copilot/gpt-4o",
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
  const payload = {
    directory,
    properties: { sessionID: "session-notice-1" },
    output: { output: "Done shipping the change." },
  };

  await hook.event("session.idle", payload);

  assert.match(payload.output.output, /^\[\d{4}-\d{1,2}-\d{1,2} \d{2}:\d{2}:\d{2}\]\n\[llm-decision-runtime\] LLM helper unavailable;/);
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

test("assistant-message-timestamp skips already-prefixed text-complete output", async () => {
  const timestamp = Date.parse("2026-03-13T12:34:56.000Z");
  const hook = createAssistantMessageTimestampHook({ enabled: true, now: () => timestamp });
  const existing = formatAssistantMessageTimestamp(timestamp);
  const payload = {
    output: {
      text: `${existing}\nStill here.`,
    },
  };

  await hook.event("experimental.text.complete", payload);

  assert.equal(payload.output.text, `${existing}\nStill here.`);
});

test("gateway-core dispatches experimental.text.complete to the timestamp hook", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-assistant-timestamp-"));
  try {
    const plugin = GatewayCorePlugin({ directory });
    const output = { text: "Octopuses have three hearts." };

    await plugin["experimental.text.complete"](
      { sessionID: "s1", messageID: "m1", partID: "p1" },
      output,
    );

    assert.match(output.text, /^\[\d{4}-\d{1,2}-\d{1,2} \d{2}:\d{2}:\d{2}\]\nOctopuses have three hearts\.$/);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});
