import type { GatewayHook } from "../registry.js";
export declare function createRetryBudgetGuardHook(options: {
    enabled: boolean;
    maxRetries: number;
}): GatewayHook;
