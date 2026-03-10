import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { dispatchGatewayHookEvent } from "../dist/hooks/shared/hook-dispatch.js";

test("hook dispatch swallows noncritical hook failures", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-hook-dispatch-"));
  const previousWrite = process.stderr.write;
  process.stderr.write = () => true;
  try {
    const result = await dispatchGatewayHookEvent({
      hook: {
        id: "task-resume-info",
        priority: 1,
        async event() {
          throw new Error("noncritical failure");
        },
      },
      eventType: "tool.execute.after",
      payload: {},
      directory,
    });
    assert.equal(result.ok, false);
    assert.equal(result.critical, false);
    assert.match(String(result.error?.message ?? ""), /noncritical failure/);
  } finally {
    process.stderr.write = previousWrite;
    rmSync(directory, { recursive: true, force: true });
  }
});

test("hook dispatch flags critical hook failures", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-hook-dispatch-"));
  const previousWrite = process.stderr.write;
  process.stderr.write = () => true;
  try {
    const result = await dispatchGatewayHookEvent({
      hook: {
        id: "dangerous-command-guard",
        priority: 1,
        async event() {
          throw new Error("critical failure");
        },
      },
      eventType: "tool.execute.before",
      payload: {},
      directory,
    });
    assert.equal(result.ok, false);
    assert.equal(result.critical, true);
    assert.match(String(result.error?.message ?? ""), /critical failure/);
  } finally {
    process.stderr.write = previousWrite;
    rmSync(directory, { recursive: true, force: true });
  }
});

test("hook dispatch does not misclassify generic runtime 'must' errors as policy blocks", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-hook-dispatch-"));
  const previousWrite = process.stderr.write;
  process.stderr.write = () => true;
  try {
    const result = await dispatchGatewayHookEvent({
      hook: {
        id: "task-resume-info",
        priority: 1,
        async event() {
          throw new Error("prompt must be defined");
        },
      },
      eventType: "tool.execute.after",
      payload: {},
      directory,
    });
    assert.equal(result.ok, false);
    assert.equal(result.critical, false);
    assert.equal(result.blocked, false);
  } finally {
    process.stderr.write = previousWrite;
    rmSync(directory, { recursive: true, force: true });
  }
});
