export declare const HOOK_DISPATCH_LATENCY_BUCKETS_MS: readonly number[];
export declare const HOOK_DISPATCH_LATENCY_EVENT_CLASSES: readonly ["tool_before", "tool_before_error", "tool_after", "command_before", "command_after", "chat_message", "chat_messages_transform", "chat_system_transform", "text_complete", "session", "message", "tool_lifecycle", "other"];
export type HookDispatchLatencyEventClass = (typeof HOOK_DISPATCH_LATENCY_EVENT_CLASSES)[number];
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
    publish: (records: readonly Record<string, unknown>[], complete: (success: boolean) => void) => boolean;
}
export declare function hookDispatchLatencyEventClass(eventType: string): HookDispatchLatencyEventClass;
export declare class HookDispatchLatencyCollector implements HookDispatchLatencyRecorder {
    private readonly enabled;
    private readonly windowMs;
    private readonly minimumSamples;
    private readonly allowedHookIds;
    private readonly now;
    private readonly schedule;
    private readonly publish;
    private activeWindow;
    private readonly detachedWindows;
    private drainScheduled;
    private publicationInFlight;
    private losses;
    constructor(options: HookDispatchLatencyCollectorOptions);
    start(): number | null;
    capture(startedAt: number | null): HookDispatchLatencyMeasurement | null;
    record(input: {
        hookId: string;
        eventType: string;
        outcome: HookDispatchLatencyOutcome;
        measurement: HookDispatchLatencyMeasurement | null;
    }): void;
    private recordSafely;
    private enqueueDetachedWindow;
    private scheduleDrain;
    private drainOne;
    private buildWindowRecords;
    flushPendingForTest(): void;
    statsForTest(): HookDispatchLatencyCollectorStats;
}
export declare function createHookDispatchLatencyCollector(options: HookDispatchLatencyCollectorOptions): HookDispatchLatencyCollector;
export {};
