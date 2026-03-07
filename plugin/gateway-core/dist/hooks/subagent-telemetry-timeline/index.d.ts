import type { GatewayHook } from "../registry.js";
export declare function createSubagentTelemetryTimelineHook(options: {
    directory: string;
    enabled: boolean;
    maxTimelineEntries: number;
}): GatewayHook;
