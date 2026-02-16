import type { GatewayHook } from "../registry.js";
export declare function createBranchFreshnessGuardHook(options: {
    directory: string;
    enabled: boolean;
    baseRef: string;
    maxBehind: number;
    enforceOnPrCreate: boolean;
    enforceOnPrMerge: boolean;
}): GatewayHook;
