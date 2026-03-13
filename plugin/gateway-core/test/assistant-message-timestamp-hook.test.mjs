import assert from "node:assert/strict";
import test from "node:test";

import {
  createAssistantMessageTimestampHook,
  formatAssistantMessageTimestamp,
} from "../dist/hooks/assistant-message-timestamp/index.js";

test("assistant-message-timestamp prepends a one-line sortable local timestamp to assistant output", async () => {
  const timestamp = Date.parse("2026-03-13T12:34:56.000Z");
  const hook = createAssistantMessageTimestampHook({
    enabled: true,
    now: () => timestamp,
  });
  const payload = {
    output: {
      output: "Done shipping the change.",
    },
  };

  await hook.event("session.idle", payload);

  assert.equal(
    payload.output.output,
    `${formatAssistantMessageTimestamp(timestamp)}\nDone shipping the change.`,
  );
});

test("assistant-message-timestamp skips empty and already-prefixed output", async () => {
  const timestamp = Date.parse("2026-03-13T12:34:56.000Z");
  const hook = createAssistantMessageTimestampHook({
    enabled: true,
    now: () => timestamp,
  });
  const existing = formatAssistantMessageTimestamp(timestamp);
  const emptyPayload = { output: { output: "   " } };
  const prefixedPayload = { output: { output: `${existing}\nStill here.` } };

  await hook.event("session.idle", emptyPayload);
  await hook.event("session.idle", prefixedPayload);

  assert.equal(emptyPayload.output.output, "   ");
  assert.equal(prefixedPayload.output.output, `${existing}\nStill here.`);
});
