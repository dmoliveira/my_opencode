import { performance } from "node:perf_hooks";

export const HOOK_DISPATCH_LATENCY_BUCKETS_MS = Object.freeze([
  1, 2, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000,
]);

export const HOOK_DISPATCH_LATENCY_EVENT_CLASSES = Object.freeze([
  "tool_before",
  "tool_before_error",
  "tool_after",
  "command_before",
  "command_after",
  "chat_message",
  "chat_messages_transform",
  "chat_system_transform",
  "text_complete",
  "session",
  "message",
  "tool_lifecycle",
  "other",
] as const);

export type HookDispatchLatencyEventClass =
  (typeof HOOK_DISPATCH_LATENCY_EVENT_CLASSES)[number];
export type HookDispatchLatencyOutcome = "success" | "failure" | "blocked";

export interface HookDispatchLatencyMeasurement {
  completedAt: number;
  durationMs: number;
}

export interface HookDispatchLatencyRecorder {
  start(): number | null;
  capture(startedAt: number | null): HookDispatchLatencyMeasurement | null;
  record(input: {
    hookId: string;
    eventType: string;
    outcome: HookDispatchLatencyOutcome;
    measurement: HookDispatchLatencyMeasurement | null;
  }): void;
}

interface HookDispatchLatencySeries {
  bucketCounts: number[];
  overflowCount: number;
  sampleCount: number;
  successCount: number;
  failureCount: number;
  blockedCount: number;
  elapsedTotalMs: number;
}

interface HookDispatchLatencyWindow {
  startedAt: number;
  series: Map<string, HookDispatchLatencySeries>;
  eventClassElapsedMs: Map<HookDispatchLatencyEventClass, number>;
}

interface PercentileEstimate {
  upperBoundMs: number | null;
  overflow: boolean;
}

interface BuiltAggregate {
  candidate: boolean;
  hook: string;
  eventClass: HookDispatchLatencyEventClass;
  sharePct: number;
  record: Record<string, unknown>;
}

interface LossCounters {
  detachedWindowsDropped: number;
  auditBatchesRejected: number;
  auditBatchesFailed: number;
  seriesSamplesDropped: number;
}

export interface HookDispatchLatencyCollectorStats extends LossCounters {
  activeSeries: number;
  detachedWindows: number;
  drainScheduled: boolean;
  publicationInFlight: boolean;
}

export interface HookDispatchLatencyCollectorOptions {
  enabled: boolean;
  windowMs: number;
  minimumSamples: number;
  allowedHookIds: readonly string[];
  now?: () => number;
  schedule?: (callback: () => void) => void;
  publish: (
    records: readonly Record<string, unknown>[],
    complete: (success: boolean) => void,
  ) => boolean;
}

const MAX_SERIES_PER_WINDOW = 2048;
const MAX_DETACHED_WINDOWS = 2;
const MAX_AGGREGATES_PER_WINDOW = 128;
const LATENCY_SHARE_GATE_PCT = 10;
const P50_GATE_MS = 10;
const P95_GATE_MS = 50;
const P99_GATE_MS = 250;

function defaultSchedule(callback: () => void): void {
  const handle = setImmediate(callback);
  handle.unref?.();
}

function eventClass(eventType: string): HookDispatchLatencyEventClass {
  switch (eventType) {
    case "tool.execute.before":
      return "tool_before";
    case "tool.execute.before.error":
      return "tool_before_error";
    case "tool.execute.after":
      return "tool_after";
    case "command.execute.before":
      return "command_before";
    case "command.execute.after":
      return "command_after";
    case "chat.message":
      return "chat_message";
    case "experimental.chat.messages.transform":
      return "chat_messages_transform";
    case "experimental.chat.system.transform":
      return "chat_system_transform";
    case "experimental.text.complete":
      return "text_complete";
    default:
      if (eventType.startsWith("session.")) {
        return "session";
      }
      if (eventType.startsWith("message.")) {
        return "message";
      }
      if (eventType.startsWith("tool.")) {
        return "tool_lifecycle";
      }
      return "other";
  }
}

function emptySeries(): HookDispatchLatencySeries {
  return {
    bucketCounts: HOOK_DISPATCH_LATENCY_BUCKETS_MS.map(() => 0),
    overflowCount: 0,
    sampleCount: 0,
    successCount: 0,
    failureCount: 0,
    blockedCount: 0,
    elapsedTotalMs: 0,
  };
}

function emptyWindow(startedAt: number): HookDispatchLatencyWindow {
  return {
    startedAt,
    series: new Map(),
    eventClassElapsedMs: new Map(),
  };
}

function seriesKey(
  hookId: string,
  value: HookDispatchLatencyEventClass,
): string {
  return `${hookId}\u0000${value}`;
}

function percentileEstimate(
  series: HookDispatchLatencySeries,
  percentile: number,
): PercentileEstimate {
  const rank = Math.ceil(percentile * series.sampleCount);
  let cumulative = 0;
  for (const [index, count] of series.bucketCounts.entries()) {
    cumulative += count;
    if (cumulative >= rank) {
      return {
        upperBoundMs: HOOK_DISPATCH_LATENCY_BUCKETS_MS[index] ?? null,
        overflow: false,
      };
    }
  }
  return { upperBoundMs: null, overflow: true };
}

function roundedSharePct(elapsedMs: number, denominatorMs: number): number {
  if (!(denominatorMs > 0)) {
    return 0;
  }
  return Math.round((elapsedMs / denominatorMs) * 10_000) / 100;
}

function gateNames(input: {
  p50: PercentileEstimate;
  p95: PercentileEstimate;
  p99: PercentileEstimate;
}): string[] {
  const output: string[] = [];
  if (
    input.p50.overflow ||
    (input.p50.upperBoundMs !== null && input.p50.upperBoundMs > P50_GATE_MS)
  ) {
    output.push("p50");
  }
  if (
    input.p95.overflow ||
    (input.p95.upperBoundMs !== null && input.p95.upperBoundMs > P95_GATE_MS)
  ) {
    output.push("p95");
  }
  if (
    input.p99.overflow ||
    (input.p99.upperBoundMs !== null && input.p99.upperBoundMs > P99_GATE_MS)
  ) {
    output.push("p99");
  }
  return output;
}

export function hookDispatchLatencyEventClass(
  eventType: string,
): HookDispatchLatencyEventClass {
  return eventClass(eventType);
}

export class HookDispatchLatencyCollector
  implements HookDispatchLatencyRecorder
{
  private readonly enabled: boolean;
  private readonly windowMs: number;
  private readonly minimumSamples: number;
  private readonly allowedHookIds: ReadonlySet<string>;
  private readonly now: () => number;
  private readonly schedule: (callback: () => void) => void;
  private readonly publish: (
    records: readonly Record<string, unknown>[],
    complete: (success: boolean) => void,
  ) => boolean;
  private activeWindow: HookDispatchLatencyWindow | null = null;
  private readonly detachedWindows: HookDispatchLatencyWindow[] = [];
  private drainScheduled = false;
  private publicationInFlight = false;
  private losses: LossCounters = {
    detachedWindowsDropped: 0,
    auditBatchesRejected: 0,
    auditBatchesFailed: 0,
    seriesSamplesDropped: 0,
  };

  constructor(options: HookDispatchLatencyCollectorOptions) {
    this.enabled = options.enabled;
    this.windowMs = options.windowMs;
    this.minimumSamples = options.minimumSamples;
    this.allowedHookIds = new Set(options.allowedHookIds);
    this.now = options.now ?? ((): number => performance.now());
    this.schedule = options.schedule ?? defaultSchedule;
    this.publish = options.publish;
  }

  start(): number | null {
    if (!this.enabled) {
      return null;
    }
    try {
      const value = this.now();
      return Number.isFinite(value) ? value : null;
    } catch {
      return null;
    }
  }

  capture(startedAt: number | null): HookDispatchLatencyMeasurement | null {
    if (!this.enabled || startedAt === null || !Number.isFinite(startedAt)) {
      return null;
    }
    try {
      const completedAt = this.now();
      const durationMs = completedAt - startedAt;
      if (
        !Number.isFinite(completedAt) ||
        !Number.isFinite(durationMs) ||
        durationMs < 0
      ) {
        return null;
      }
      return { completedAt, durationMs };
    } catch {
      return null;
    }
  }

  record(input: {
    hookId: string;
    eventType: string;
    outcome: HookDispatchLatencyOutcome;
    measurement: HookDispatchLatencyMeasurement | null;
  }): void {
    try {
      this.recordSafely(input);
    } catch {
      // Measurement must never alter hook dispatch behavior.
    }
  }

  private recordSafely(input: {
    hookId: string;
    eventType: string;
    outcome: HookDispatchLatencyOutcome;
    measurement: HookDispatchLatencyMeasurement | null;
  }): void {
    const measurement = input.measurement;
    if (
      !this.enabled ||
      measurement === null ||
      !this.allowedHookIds.has(input.hookId)
    ) {
      return;
    }

    if (this.activeWindow === null) {
      this.activeWindow = emptyWindow(measurement.completedAt);
    } else if (
      measurement.completedAt - this.activeWindow.startedAt >=
      this.windowMs
    ) {
      const completed = this.activeWindow;
      this.activeWindow = emptyWindow(measurement.completedAt);
      this.enqueueDetachedWindow(completed);
    }

    const current = this.activeWindow;
    const currentEventClass = eventClass(input.eventType);
    current.eventClassElapsedMs.set(
      currentEventClass,
      Math.min(
        Number.MAX_SAFE_INTEGER,
        (current.eventClassElapsedMs.get(currentEventClass) ?? 0) +
          measurement.durationMs,
      ),
    );

    const key = seriesKey(input.hookId, currentEventClass);
    let series = current.series.get(key);
    if (!series) {
      if (current.series.size >= MAX_SERIES_PER_WINDOW) {
        this.losses.seriesSamplesDropped += 1;
        return;
      }
      series = emptySeries();
      current.series.set(key, series);
    }

    series.sampleCount += 1;
    series.elapsedTotalMs = Math.min(
      Number.MAX_SAFE_INTEGER,
      series.elapsedTotalMs + measurement.durationMs,
    );
    if (input.outcome === "success") {
      series.successCount += 1;
    } else if (input.outcome === "blocked") {
      series.blockedCount += 1;
    } else {
      series.failureCount += 1;
    }
    const bucketIndex = HOOK_DISPATCH_LATENCY_BUCKETS_MS.findIndex(
      (upperBound) => measurement.durationMs <= upperBound,
    );
    if (bucketIndex < 0) {
      series.overflowCount += 1;
    } else {
      series.bucketCounts[bucketIndex] += 1;
    }
  }

  private enqueueDetachedWindow(window: HookDispatchLatencyWindow): void {
    if (window.series.size === 0) {
      return;
    }
    if (this.detachedWindows.length >= MAX_DETACHED_WINDOWS) {
      this.losses.detachedWindowsDropped += 1;
      return;
    }
    this.detachedWindows.push(window);
    this.scheduleDrain();
  }

  private scheduleDrain(): void {
    if (
      this.drainScheduled ||
      this.publicationInFlight ||
      this.detachedWindows.length === 0
    ) {
      return;
    }
    this.drainScheduled = true;
    try {
      this.schedule(() => {
        this.drainScheduled = false;
        this.drainOne();
        this.scheduleDrain();
      });
    } catch {
      this.drainScheduled = false;
      this.losses.detachedWindowsDropped += this.detachedWindows.length;
      this.detachedWindows.splice(0, this.detachedWindows.length);
    }
  }

  private drainOne(): void {
    const window = this.detachedWindows.shift();
    if (!window) {
      return;
    }
    const records = this.buildWindowRecords(window);
    if (records.length === 0) {
      return;
    }
    const lossSnapshot = { ...this.losses };
    let completed = false;
    const complete = (success: boolean): void => {
      if (completed) {
        return;
      }
      completed = true;
      this.publicationInFlight = false;
      if (success) {
        this.losses.detachedWindowsDropped = Math.max(
          0,
          this.losses.detachedWindowsDropped -
            lossSnapshot.detachedWindowsDropped,
        );
        this.losses.auditBatchesRejected = Math.max(
          0,
          this.losses.auditBatchesRejected - lossSnapshot.auditBatchesRejected,
        );
        this.losses.auditBatchesFailed = Math.max(
          0,
          this.losses.auditBatchesFailed - lossSnapshot.auditBatchesFailed,
        );
        this.losses.seriesSamplesDropped = Math.max(
          0,
          this.losses.seriesSamplesDropped - lossSnapshot.seriesSamplesDropped,
        );
      } else {
        this.losses.auditBatchesFailed += 1;
      }
      this.scheduleDrain();
    };

    this.publicationInFlight = true;
    let accepted = false;
    try {
      accepted = this.publish(records, complete);
    } catch {
      accepted = false;
    }
    if (!accepted && !completed) {
      this.publicationInFlight = false;
      this.losses.auditBatchesRejected += 1;
      this.scheduleDrain();
    }
  }

  private buildWindowRecords(
    window: HookDispatchLatencyWindow,
  ): Record<string, unknown>[] {
    const built: BuiltAggregate[] = [];
    for (const [key, series] of window.series.entries()) {
      if (series.sampleCount < this.minimumSamples) {
        continue;
      }
      const separator = key.indexOf("\u0000");
      const hook = key.slice(0, separator);
      const currentEventClass = key.slice(
        separator + 1,
      ) as HookDispatchLatencyEventClass;
      const denominator = window.eventClassElapsedMs.get(currentEventClass) ?? 0;
      const elapsedTotalMs = Math.round(series.elapsedTotalMs);
      const eventClassElapsedTotalMs = Math.round(denominator);
      const sharePct = roundedSharePct(
        elapsedTotalMs,
        eventClassElapsedTotalMs,
      );
      const p50 = percentileEstimate(series, 0.5);
      const p95 = percentileEstimate(series, 0.95);
      const p99 = percentileEstimate(series, 0.99);
      const exceededGates = gateNames({ p50, p95, p99 });
      const candidate =
        sharePct > LATENCY_SHARE_GATE_PCT && exceededGates.length > 0;
      built.push({
        candidate,
        hook,
        eventClass: currentEventClass,
        sharePct,
        record: {
          hook,
          stage: "aggregate",
          reason_code: "hook_dispatch_latency_window",
          event_class: currentEventClass,
          window_ms: this.windowMs,
          minimum_samples: this.minimumSamples,
          sample_count: series.sampleCount,
          success_count: series.successCount,
          failure_count: series.failureCount,
          blocked_count: series.blockedCount,
          bucket_upper_bounds_ms: [...HOOK_DISPATCH_LATENCY_BUCKETS_MS],
          bucket_counts: [...series.bucketCounts],
          overflow_count: series.overflowCount,
          elapsed_total_ms: elapsedTotalMs,
          event_class_elapsed_total_ms: eventClassElapsedTotalMs,
          p50_upper_bound_ms: p50.upperBoundMs,
          p50_overflow: p50.overflow,
          p95_upper_bound_ms: p95.upperBoundMs,
          p95_overflow: p95.overflow,
          p99_upper_bound_ms: p99.upperBoundMs,
          p99_overflow: p99.overflow,
          latency_share_pct: sharePct,
          optimization_candidate: candidate,
          candidate_gate_names: exceededGates,
        },
      });
    }

    built.sort((left, right) => {
      if (left.candidate !== right.candidate) {
        return left.candidate ? -1 : 1;
      }
      if (left.sharePct !== right.sharePct) {
        return right.sharePct - left.sharePct;
      }
      return (
        left.hook.localeCompare(right.hook) ||
        left.eventClass.localeCompare(right.eventClass)
      );
    });
    const selected = built.slice(0, MAX_AGGREGATES_PER_WINDOW);
    const windowSeriesDropped = built.length - selected.length;
    return selected.map(({ record }) => ({
      ...record,
      window_series_total: built.length,
      window_series_enqueued: selected.length,
      window_series_dropped: windowSeriesDropped,
      detached_windows_dropped: this.losses.detachedWindowsDropped,
      audit_batches_rejected: this.losses.auditBatchesRejected,
      audit_batches_failed: this.losses.auditBatchesFailed,
      series_samples_dropped: this.losses.seriesSamplesDropped,
    }));
  }

  flushPendingForTest(): void {
    this.drainScheduled = false;
    while (this.detachedWindows.length > 0) {
      this.drainOne();
    }
  }

  statsForTest(): HookDispatchLatencyCollectorStats {
    return {
      ...this.losses,
      activeSeries: this.activeWindow?.series.size ?? 0,
      detachedWindows: this.detachedWindows.length,
      drainScheduled: this.drainScheduled,
      publicationInFlight: this.publicationInFlight,
    };
  }
}

export function createHookDispatchLatencyCollector(
  options: HookDispatchLatencyCollectorOptions,
): HookDispatchLatencyCollector {
  return new HookDispatchLatencyCollector(options);
}
