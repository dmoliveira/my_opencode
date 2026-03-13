import assert from "node:assert/strict";
import test from "node:test";

import {
  createAssistantMessageTimestampHook,
  formatAssistantMessageTimestamp,
} from "../dist/hooks/assistant-message-timestamp/index.js";

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
})

test("assistant-message-timestamp inserts a text part when latest assistant transform message has no text parts", async () => {
  const timestamp = Date.parse("2026-03-13T12:34:56.000Z");
  const hook = createAssistantMessageTimestampHook({
    enabled: true,
    now: () => timestamp,
  });
  const payload = {
    output: {
      messages: [
        { info: { role: "assistant" }, parts: [{ type: "tool-call", text: "ignored" }] },
      ],
    },
  };

  await hook.event("experimental.chat.messages.transform", payload);

  assert.equal(payload.output.messages[0].parts[0].text, formatAssistantMessageTimestamp(timestamp));
})

test("assistant-message-timestamp skips empty and already-prefixed output", async () => {
  const timestamp = Date.parse("2026-03-13T12:34:56.000Z");
  const hook = createAssistantMessageTimestampHook({
    enabled: true,
    now: () => timestamp,
  });
  const existing = formatAssistantMessageTimestamp(timestamp);
  const emptyPayload = { output: { output: "   " } };
  const prefixedPayload = { output: { output: `${existing}\nStill here.` } };
  const transformPayload = {
    output: {
      messages: [{ info: { role: "assistant" }, parts: [{ type: "text", text: `${existing}\nStill here.` }] }],
    },
  };

  await hook.event("session.idle", emptyPayload);
  await hook.event("session.idle", prefixedPayload);
  await hook.event("experimental.chat.messages.transform", transformPayload);

  assert.equal(emptyPayload.output.output, "   ");
  assert.equal(prefixedPayload.output.output, `${existing}\nStill here.`);
  assert.equal(transformPayload.output.messages[0].parts[0].text, `${existing}\nStill here.`);
})
