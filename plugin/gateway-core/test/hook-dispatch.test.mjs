import assert from "node:assert/strict";
import {
  lstatSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
} from "node:fs";
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

test("hook dispatch treats known tool-disable wording as intentional block", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-hook-dispatch-"));
  const previousWrite = process.stderr.write;
  process.stderr.write = () => true;
  try {
    const result = await dispatchGatewayHookEvent({
      hook: {
        id: "tasks-todowrite-disabler",
        priority: 1,
        async event() {
          throw new Error(
            "Task/TodoWrite tools are disabled in this workflow by gateway configuration.",
          );
        },
      },
      eventType: "tool.execute.before",
      payload: {},
      directory,
    });
    assert.equal(result.ok, false);
    assert.equal(result.blocked, true);
  } finally {
    process.stderr.write = previousWrite;
    rmSync(directory, { recursive: true, force: true });
  }
});

test("hook dispatch does not treat generic feature-disabled wording as intentional block", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-hook-dispatch-"));
  const previousWrite = process.stderr.write;
  process.stderr.write = () => true;
  try {
    const result = await dispatchGatewayHookEvent({
      hook: {
        id: "task-resume-info",
        priority: 1,
        async event() {
          throw new Error("feature disabled by config");
        },
      },
      eventType: "tool.execute.after",
      payload: {},
      directory,
    });
    assert.equal(result.ok, false);
    assert.equal(result.blocked, false);
  } finally {
    process.stderr.write = previousWrite;
    rmSync(directory, { recursive: true, force: true });
  }
});

test("hook dispatch does not treat generic must-include wording as intentional block", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-hook-dispatch-"));
  const previousWrite = process.stderr.write;
  process.stderr.write = () => true;
  try {
    const result = await dispatchGatewayHookEvent({
      hook: {
        id: "task-resume-info",
        priority: 1,
        async event() {
          throw new Error("payload must include a session id");
        },
      },
      eventType: "tool.execute.after",
      payload: {},
      directory,
    });
    assert.equal(result.ok, false);
    assert.equal(result.blocked, false);
  } finally {
    process.stderr.write = previousWrite;
    rmSync(directory, { recursive: true, force: true });
  }
});

test("hook dispatch sanitizes secret failure details before audit and stderr", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-hook-dispatch-"));
  const previousAudit = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT;
  const previousOtel = process.env.MY_OPENCODE_OTEL_EXPORT_ENABLED;
  const previousStderr = process.env.MY_OPENCODE_GATEWAY_HOOK_FAILURE_STDERR;
  const previousWrite = process.stderr.write;
  let surfaced = "";
  process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = "1";
  process.env.MY_OPENCODE_OTEL_EXPORT_ENABLED = "0";
  process.env.MY_OPENCODE_GATEWAY_HOOK_FAILURE_STDERR = "1";
  process.stderr.write = (chunk) => {
    surfaced += String(chunk);
    return true;
  };
  try {
    const result = await dispatchGatewayHookEvent({
      hook: {
        id: "task-resume-info",
        priority: 1,
        async event() {
          throw new Error(
            "Authorization=Basic dispatch-authorization-canary token=dispatch-token-canary",
          );
        },
      },
      eventType: "tool.execute.after",
      payload: {},
      directory,
    });
    assert.equal(result.ok, false);
    assert.equal(surfaced.includes("dispatch-authorization-canary"), false);
    assert.equal(surfaced.includes("dispatch-token-canary"), false);
    assert.match(surfaced, /\[REDACTED\]/);

    const entries = readFileSync(
      join(directory, ".opencode", "gateway-events.jsonl"),
      "utf-8",
    )
      .split(/\r?\n/)
      .filter(Boolean)
      .map((line) => JSON.parse(line));
    assert.equal(entries.at(-1)?.error_message, "[REDACTED]");
    assert.equal(
      JSON.stringify(entries).includes("dispatch-authorization-canary"),
      false,
    );
    assert.equal(
      JSON.stringify(entries).includes("dispatch-token-canary"),
      false,
    );
  } finally {
    process.stderr.write = previousWrite;
    if (previousAudit === undefined) {
      delete process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT;
    } else {
      process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = previousAudit;
    }
    if (previousOtel === undefined) {
      delete process.env.MY_OPENCODE_OTEL_EXPORT_ENABLED;
    } else {
      process.env.MY_OPENCODE_OTEL_EXPORT_ENABLED = previousOtel;
    }
    if (previousStderr === undefined) {
      delete process.env.MY_OPENCODE_GATEWAY_HOOK_FAILURE_STDERR;
    } else {
      process.env.MY_OPENCODE_GATEWAY_HOOK_FAILURE_STDERR = previousStderr;
    }
    rmSync(directory, { recursive: true, force: true });
  }
});

test("hook dispatch preserves the original result when the audit sink is unsafe", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-hook-dispatch-"));
  const previousAudit = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT;
  const previousAuditPath = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT_PATH;
  const previousOtel = process.env.MY_OPENCODE_OTEL_EXPORT_ENABLED;
  const previousWrite = process.stderr.write;
  const unsafePath = join(directory, "gateway-events-as-directory");
  mkdirSync(unsafePath, { mode: 0o700 });
  process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = "1";
  process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT_PATH = unsafePath;
  process.env.MY_OPENCODE_OTEL_EXPORT_ENABLED = "0";
  process.stderr.write = () => true;
  try {
    const result = await dispatchGatewayHookEvent({
      hook: {
        id: "task-resume-info",
        priority: 1,
        async event() {
          throw new Error("original hook failure");
        },
      },
      eventType: "tool.execute.after",
      payload: {},
      directory,
    });
    assert.equal(result.ok, false);
    assert.equal(result.critical, false);
    assert.equal(result.blocked, false);
    assert.match(result.error?.message ?? "", /original hook failure/);
    assert.equal(lstatSync(unsafePath).isDirectory(), true);
  } finally {
    process.stderr.write = previousWrite;
    if (previousAudit === undefined) {
      delete process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT;
    } else {
      process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = previousAudit;
    }
    if (previousAuditPath === undefined) {
      delete process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT_PATH;
    } else {
      process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT_PATH = previousAuditPath;
    }
    if (previousOtel === undefined) {
      delete process.env.MY_OPENCODE_OTEL_EXPORT_ENABLED;
    } else {
      process.env.MY_OPENCODE_OTEL_EXPORT_ENABLED = previousOtel;
    }
    rmSync(directory, { recursive: true, force: true });
  }
});
