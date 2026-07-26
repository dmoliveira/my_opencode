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
export declare function writeGatewayEventAudit(directory: string, entry: Record<string, unknown>): void;
export {};
