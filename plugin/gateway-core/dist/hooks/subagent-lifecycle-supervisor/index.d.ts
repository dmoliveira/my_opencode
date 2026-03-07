import type { GatewayHook } from "../registry.js";
export declare function createSubagentLifecycleSupervisorHook(options: {
    directory: string;
    enabled: boolean;
    maxRetriesPerSession: number;
    staleRunningMs: number;
    blockOnExhausted: boolean;
}): GatewayHook;
