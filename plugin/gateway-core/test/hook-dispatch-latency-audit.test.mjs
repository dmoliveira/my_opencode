import assert from "node:assert/strict";
import {
  existsSync,
  lstatSync,
  mkdtempSync,
  readFileSync,
  rmSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import {
  enqueueGatewayLocalAggregateAudit,
  flushGatewayLocalAggregateAuditForTest,
  gatewayLocalAggregateAuditQueueSizeForTest,
  resetGatewayEventAuditStateForTest,
} from "../dist/audit/event-audit.js";
import { HookDispatchLatencyCollector } from "../dist/hooks/shared/hook-dispatch-latency.js";

function withAuditEnvironment(run) {
  const directory = mkdtempSync(join(tmpdir(), "gateway-latency-audit-"));
  const path = join(directory, "aggregate.jsonl");
  const previous = {
    audit: process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT,
    path: process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT_PATH,
    otel: process.env.MY_OPENCODE_OTEL_EXPORT_ENABLED,
  };
  process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = "1";
  process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT_PATH = path;
  process.env.MY_OPENCODE_OTEL_EXPORT_ENABLED = "1";
  resetGatewayEventAuditStateForTest();
  try {
    return run({ directory, path });
  } finally {
    resetGatewayEventAuditStateForTest();
    for (const [key, value] of Object.entries(previous)) {
      const envKey = {
        audit: "MY_OPENCODE_GATEWAY_EVENT_AUDIT",
        path: "MY_OPENCODE_GATEWAY_EVENT_AUDIT_PATH",
        otel: "MY_OPENCODE_OTEL_EXPORT_ENABLED",
      }[key];
      if (value === undefined) {
        delete process.env[envKey];
      } else {
        process.env[envKey] = value;
      }
    }
    rmSync(directory, { recursive: true, force: true });
  }
}

test("aggregate audit batches are asynchronous, local-only, and sanitized", () => {
  withAuditEnvironment(({ directory, path }) => {
    const previousFetch = globalThis.fetch;
    let fetchCalls = 0;
    let completion = null;
    globalThis.fetch = async () => {
      fetchCalls += 1;
      return { ok: true, status: 200 };
    };
    try {
      assert.equal(
        enqueueGatewayLocalAggregateAudit(directory, [
          {
            hook: "continuation",
            stage: "aggregate",
            reason_code: "hook_dispatch_latency_window",
            event_class: "session",
            sample_count: 100,
            prompt: "latency-prompt-canary",
            session_id: "latency-session-canary",
          },
        ], (success) => {
          completion = success;
        }),
        true,
      );
      assert.equal(existsSync(path), false);
      assert.equal(gatewayLocalAggregateAuditQueueSizeForTest(), 1);

      flushGatewayLocalAggregateAuditForTest();
      const text = readFileSync(path, "utf8");
      const record = JSON.parse(text.trim());
      assert.equal(record.hook, "continuation");
      assert.equal(record.reason_code, "hook_dispatch_latency_window");
      assert.equal(text.includes("latency-prompt-canary"), false);
      assert.equal(text.includes("latency-session-canary"), false);
      assert.equal(lstatSync(directory).mode & 0o777, 0o700);
      assert.equal(lstatSync(path).mode & 0o777, 0o600);
      assert.equal(fetchCalls, 0);
      assert.equal(completion, true);
    } finally {
      globalThis.fetch = previousFetch;
    }
  });
});

test("collector rollover reaches one aggregate-only owner-private audit batch", () => {
  withAuditEnvironment(({ directory, path }) => {
    let clock = 0;
    const scheduled = [];
    const collector = new HookDispatchLatencyCollector({
      enabled: true,
      windowMs: 60_000,
      minimumSamples: 20,
      allowedHookIds: ["continuation"],
      now: () => clock,
      schedule: (callback) => scheduled.push(callback),
      publish: (records, complete) =>
        enqueueGatewayLocalAggregateAudit(directory, records, complete),
    });
    const observe = () => {
      const startedAt = collector.start();
      clock += 500;
      collector.record({
        hookId: "continuation",
        eventType: "session.idle",
        outcome: "success",
        measurement: collector.capture(startedAt),
      });
    };
    for (let index = 0; index < 20; index += 1) {
      observe();
    }
    clock += 60_000;
    observe();

    assert.equal(existsSync(path), false);
    assert.equal(scheduled.length, 1);
    scheduled.shift()();
    assert.equal(gatewayLocalAggregateAuditQueueSizeForTest(), 1);
    flushGatewayLocalAggregateAuditForTest();

    const lines = readFileSync(path, "utf8").trim().split(/\r?\n/);
    assert.equal(lines.length, 1);
    const record = JSON.parse(lines[0]);
    assert.equal(record.reason_code, "hook_dispatch_latency_window");
    assert.equal(record.sample_count, 20);
    assert.equal(record.event_class, "session");
    assert.equal(record.window_ms, 60_000);
  });
});

test("aggregate audit queue admits batches all-or-none and stays bounded", () => {
  withAuditEnvironment(({ directory }) => {
    const fullBatch = Array.from({ length: 256 }, (_, index) => ({
      hook: "continuation",
      reason_code: "hook_dispatch_latency_window",
      sample_count: index + 1,
    }));
    assert.equal(
      enqueueGatewayLocalAggregateAudit(directory, fullBatch, () => {}),
      true,
    );
    assert.equal(gatewayLocalAggregateAuditQueueSizeForTest(), 256);
    assert.equal(
      enqueueGatewayLocalAggregateAudit(directory, [
        { hook: "continuation", sample_count: 999 },
      ], () => {}),
      false,
    );
    assert.equal(gatewayLocalAggregateAuditQueueSizeForTest(), 256);
  });
});

test("aggregate audit flush isolates unsafe destination failures", () => {
  withAuditEnvironment(({ directory }) => {
    process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT_PATH = directory;
    resetGatewayEventAuditStateForTest();
    let completion = null;
    assert.equal(
      enqueueGatewayLocalAggregateAudit(directory, [
        {
          hook: "continuation",
          reason_code: "hook_dispatch_latency_window",
          sample_count: 100,
        },
      ], (success) => {
        completion = success;
      }),
      true,
    );
    assert.doesNotThrow(() => flushGatewayLocalAggregateAuditForTest());
    assert.equal(gatewayLocalAggregateAuditQueueSizeForTest(), 0);
    assert.equal(completion, false);
  });
});

test("aggregate queue rejects batches while file audit is disabled", () => {
  withAuditEnvironment(({ directory }) => {
    process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT = "0";
    resetGatewayEventAuditStateForTest();
    assert.equal(
      enqueueGatewayLocalAggregateAudit(directory, [
        { hook: "continuation", sample_count: 100 },
      ], () => {}),
      false,
    );
    assert.equal(gatewayLocalAggregateAuditQueueSizeForTest(), 0);
  });
});
