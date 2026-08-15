interface MutableOtelExportStats {
    enqueued: number;
    sent: number;
    succeeded: number;
    failed: number;
    timedOut: number;
    httpFailures: number;
    dropped: number;
    oversized: number;
}
export interface GatewayEventAuditExportStats extends MutableOtelExportStats {
    queued: number;
    inFlight: number;
}
export declare function sanitizeGatewayAuditText(value: unknown): string;
export declare function gatewayEventAuditExportStatsForTest(): GatewayEventAuditExportStats;
export declare function flushGatewayEventAuditExportsForTest(): Promise<void>;
export declare function resetGatewayEventAuditStateForTest(): void;
export declare function gatewayEventAuditEnabled(): boolean;
export declare function gatewayEventAuditPath(directory: string): string;
/** Queues an all-or-none local-only aggregate audit batch without OTLP export. */
export declare function enqueueGatewayLocalAggregateAudit(directory: string, entries: readonly Record<string, unknown>[], complete: (success: boolean) => void): boolean;
/** Flushes queued local aggregate audit records synchronously for tests only. */
export declare function flushGatewayLocalAggregateAuditForTest(): void;
export declare function gatewayLocalAggregateAuditQueueSizeForTest(): number;
export declare function writeGatewayLocalEventAudit(directory: string, entry: Record<string, unknown>): void;
export declare function writeGatewayEventAudit(directory: string, entry: Record<string, unknown>): void;
export {};
