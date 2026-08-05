import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { DEFAULT_GATEWAY_HOOK_ORDER } from "../dist/config/schema.js";
import {
  HOOK_DISPATCH_LATENCY_BUCKETS_MS,
  HookDispatchLatencyCollector,
  hookDispatchLatencyEventClass,
} from "../dist/hooks/shared/hook-dispatch-latency.js";

function harness({
  allowedHookIds = ["continuation"],
  autoComplete = true,
  enabled = true,
  minimumSamples = 1,
  publish = () => true,
  windowMs = 100,
} = {}) {
  let clock = 0;
  const scheduled = [];
  const publications = [];
  const collector = new HookDispatchLatencyCollector({
    enabled,
    windowMs,
    minimumSamples,
    allowedHookIds,
    now: () => clock,
    schedule: (callback) => scheduled.push(callback),
    publish: (records, complete) => {
      publications.push(records.map((record) => structuredClone(record)));
      const accepted = publish(records, publications.length, complete);
      if (accepted && autoComplete) {
        complete(true);
      }
      return accepted;
    },
  });
  const observe = ({
    durationMs = 1,
    eventType = "tool.execute.before",
    hookId = allowedHookIds[0],
    outcome = "success",
  } = {}) => {
    const startedAt = collector.start();
    clock += durationMs;
    const measurement = collector.capture(startedAt);
    collector.record({ hookId, eventType, outcome, measurement });
  };
  const advance = (durationMs) => {
    clock += durationMs;
  };
  const runNext = () => scheduled.shift()?.();
  return {
    advance,
    collector,
    observe,
    publications,
    runNext,
    scheduled,
  };
}

test("hook latency event classes stay fixed and coarse", () => {
  const cases = {
    "tool.execute.before": "tool_before",
    "tool.execute.before.error": "tool_before_error",
    "tool.execute.after": "tool_after",
    "command.execute.before": "command_before",
    "command.execute.after": "command_after",
    "chat.message": "chat_message",
    "experimental.chat.messages.transform": "chat_messages_transform",
    "experimental.chat.system.transform": "chat_system_transform",
    "experimental.text.complete": "text_complete",
    "session.idle": "session",
    "message.updated": "message",
    "tool.updated": "tool_lifecycle",
    "permission.updated": "other",
  };
  for (const [eventType, expected] of Object.entries(cases)) {
    assert.equal(hookDispatchLatencyEventClass(eventType), expected);
  }
});

test("canonical hook manifest stays synchronized with the runtime manifest", () => {
  const manifest = JSON.parse(
    readFileSync(new URL("../config/hook-ids.json", import.meta.url), "utf8"),
  );
  assert.equal(manifest.version, 1);
  assert.deepEqual(manifest.hook_ids, DEFAULT_GATEWAY_HOOK_ORDER);
});

test("every index hook dispatch path uses the latency-bound wrapper", () => {
  const source = readFileSync(new URL("../src/index.ts", import.meta.url), "utf8");
  assert.equal(source.match(/dispatchGatewayHookEvent\(\{/g)?.length, 1);
  assert.equal(source.match(/dispatchHook\(\{/g)?.length, 13);
  assert.match(source, /gatewayEventAuditEnabled\(\)/);
  assert.match(source, /enqueueGatewayLocalAggregateAudit/);
});

test("rollover detaches without publishing in the dispatch call", () => {
  const state = harness({ minimumSamples: 2 });
  state.observe({ durationMs: 2 });
  state.observe({ durationMs: 3, outcome: "failure" });
  state.advance(100);
  state.observe({ durationMs: 4 });

  assert.equal(state.publications.length, 0);
  assert.equal(state.scheduled.length, 1);
  state.runNext();
  assert.equal(state.publications.length, 1);
  const record = state.publications[0][0];
  assert.equal(record.sample_count, 2);
  assert.equal(record.success_count, 1);
  assert.equal(record.failure_count, 1);
  assert.equal(record.blocked_count, 0);
});

test("minimum sample threshold suppresses per-invocation and small-window output", () => {
  const state = harness({ minimumSamples: 100 });
  for (let index = 0; index < 99; index += 1) {
    state.observe();
  }
  state.advance(100);
  state.observe();
  state.runNext();
  assert.deepEqual(state.publications, []);

  for (let index = 0; index < 99; index += 1) {
    state.observe();
  }
  state.advance(100);
  state.observe();
  state.runNext();
  assert.equal(state.publications[0][0].sample_count, 100);
});

test("histogram percentiles, overflow, outcomes, and subthreshold share are exact", () => {
  const state = harness({
    allowedHookIds: ["continuation", "task-resume-info"],
    minimumSamples: 100,
    windowMs: 1_000_000,
  });
  for (let index = 0; index < 50; index += 1) {
    state.observe({ durationMs: 1 });
  }
  for (let index = 0; index < 45; index += 1) {
    state.observe({ durationMs: 50, outcome: "blocked" });
  }
  for (let index = 0; index < 4; index += 1) {
    state.observe({ durationMs: 250, outcome: "failure" });
  }
  state.observe({ durationMs: 20_000 });
  for (let index = 0; index < 99; index += 1) {
    state.observe({ hookId: "task-resume-info", durationMs: 100 });
  }
  state.advance(1_000_000);
  state.observe();
  state.runNext();

  const record = state.publications[0][0];
  assert.deepEqual(record.bucket_upper_bounds_ms, HOOK_DISPATCH_LATENCY_BUCKETS_MS);
  assert.equal(
    record.bucket_counts.reduce((total, count) => total + count, 0) +
      record.overflow_count,
    record.sample_count,
  );
  assert.equal(record.p50_upper_bound_ms, 1);
  assert.equal(record.p95_upper_bound_ms, 50);
  assert.equal(record.p99_upper_bound_ms, 250);
  assert.equal(record.p99_overflow, false);
  assert.equal(record.overflow_count, 1);
  assert.equal(record.success_count, 51);
  assert.equal(record.failure_count, 4);
  assert.equal(record.blocked_count, 45);
  assert.ok(record.latency_share_pct < 100);
  assert.equal(record.optimization_candidate, false);
});

test("share and percentile gates require both contributors", () => {
  const state = harness({
    allowedHookIds: ["continuation", "task-resume-info"],
    minimumSamples: 20,
    windowMs: 1_000_000,
  });
  for (let index = 0; index < 20; index += 1) {
    state.observe({ durationMs: 500 });
  }
  for (let index = 0; index < 20; index += 1) {
    state.observe({ hookId: "task-resume-info", durationMs: 10_000 });
  }
  state.advance(1_000_000);
  state.observe();
  state.runNext();

  const byHook = new Map(
    state.publications[0].map((record) => [record.hook, record]),
  );
  assert.equal(byHook.get("continuation").optimization_candidate, false);
  assert.equal(
    byHook.get("task-resume-info").optimization_candidate,
    true,
  );
  assert.deepEqual(
    byHook.get("task-resume-info").candidate_gate_names,
    ["p50", "p95", "p99"],
  );
});

test("disabled measurement performs no clock work", () => {
  let calls = 0;
  const collector = new HookDispatchLatencyCollector({
    enabled: false,
    windowMs: 100,
    minimumSamples: 1,
    allowedHookIds: ["continuation"],
    now: () => {
      calls += 1;
      throw new Error("clock should remain unused");
    },
    publish: () => {
      throw new Error("publisher should remain unused");
    },
  });
  assert.equal(collector.start(), null);
  assert.equal(collector.capture(null), null);
  collector.record({
    hookId: "continuation",
    eventType: "session.idle",
    outcome: "success",
    measurement: null,
  });
  assert.equal(calls, 0);
});

test("active measurement performs two clock reads and no sink call per dispatch", () => {
  let clock = 0;
  let clockCalls = 0;
  let publishCalls = 0;
  const collector = new HookDispatchLatencyCollector({
    enabled: true,
    windowMs: 1_000_000,
    minimumSamples: 100,
    allowedHookIds: ["continuation"],
    now: () => {
      clockCalls += 1;
      clock += 1;
      return clock;
    },
    publish: () => {
      publishCalls += 1;
      return true;
    },
  });
  for (let index = 0; index < 100; index += 1) {
    const startedAt = collector.start();
    collector.record({
      hookId: "continuation",
      eventType: "session.idle",
      outcome: "success",
      measurement: collector.capture(startedAt),
    });
  }
  assert.equal(clockCalls, 200);
  assert.equal(publishCalls, 0);
});

test("clock failures and unknown hook ids fail open without aggregate output", () => {
  let calls = 0;
  const collector = new HookDispatchLatencyCollector({
    enabled: true,
    windowMs: 100,
    minimumSamples: 1,
    allowedHookIds: ["continuation"],
    now: () => {
      calls += 1;
      throw new Error("clock failed");
    },
    publish: () => false,
  });
  assert.equal(collector.start(), null);
  assert.equal(calls, 1);
  collector.record({
    hookId: "unknown-hook",
    eventType: "session.idle",
    outcome: "success",
    measurement: { completedAt: 1, durationMs: 1 },
  });
  assert.equal(collector.statsForTest().activeSeries, 0);
});

test("detached-window and audit-batch loss is carried into the next admitted batch", () => {
  let rejectFirst = true;
  const state = harness({
    publish: () => {
      if (rejectFirst) {
        rejectFirst = false;
        return false;
      }
      return true;
    },
  });
  state.observe();
  for (let index = 0; index < 3; index += 1) {
    state.advance(100);
    state.observe();
  }
  assert.equal(state.collector.statsForTest().detachedWindowsDropped, 1);

  state.runNext();
  state.runNext();
  assert.equal(state.publications.length, 2);
  assert.equal(state.publications[1][0].detached_windows_dropped, 1);
  assert.equal(state.publications[1][0].audit_batches_rejected, 1);
  assert.equal(state.collector.statsForTest().auditBatchesRejected, 0);
});

test("failed audit completion is carried until a fully written batch", () => {
  const completions = [];
  const state = harness({
    autoComplete: false,
    publish: (_records, _count, complete) => {
      completions.push(complete);
      return true;
    },
  });
  state.observe();
  state.advance(100);
  state.observe();
  state.runNext();
  assert.equal(state.collector.statsForTest().publicationInFlight, true);
  completions.shift()(false);
  assert.equal(state.collector.statsForTest().auditBatchesFailed, 1);

  state.advance(100);
  state.observe();
  state.runNext();
  assert.equal(state.publications[1][0].audit_batches_failed, 1);
  completions.shift()(true);
  assert.equal(state.collector.statsForTest().auditBatchesFailed, 0);
});

test("publication cap selects candidates before non-candidates and reports loss", () => {
  const hookIds = Array.from({ length: 129 }, (_, index) => `hook-${index}`);
  const state = harness({
    allowedHookIds: hookIds,
    minimumSamples: 1,
    windowMs: 1_000_000,
  });
  for (const hookId of hookIds.slice(0, 128)) {
    state.observe({ hookId, durationMs: 1, eventType: "tool.execute.before" });
  }
  state.observe({
    hookId: hookIds[128],
    durationMs: 500,
    eventType: "session.idle",
  });
  state.advance(1_000_000);
  state.observe({ hookId: hookIds[0] });
  state.runNext();

  const records = state.publications[0];
  assert.equal(records.length, 128);
  assert.equal(records[0].hook, hookIds[128]);
  assert.equal(records[0].optimization_candidate, true);
  assert.equal(records[0].window_series_total, 129);
  assert.equal(records[0].window_series_enqueued, 128);
  assert.equal(records[0].window_series_dropped, 1);
});

test("active series and detached queues stay bounded", () => {
  const hookIds = Array.from({ length: 2050 }, (_, index) => `hook-${index}`);
  const state = harness({
    allowedHookIds: hookIds,
    minimumSamples: 1,
    windowMs: 1_000_000,
  });
  for (const hookId of hookIds) {
    state.observe({ hookId });
  }
  assert.equal(state.collector.statsForTest().activeSeries, 2048);
  assert.equal(state.collector.statsForTest().seriesSamplesDropped, 2);

  state.advance(1_000_000);
  state.observe({ hookId: hookIds[0] });
  state.runNext();
  assert.equal(state.publications[0][0].series_samples_dropped, 2);
});
