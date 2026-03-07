import type { GatewayHook } from "../registry.js";
export declare function createDelegationConcurrencyGuardHook(options: {
    directory: string;
    enabled: boolean;
    maxTotalConcurrent: number;
    maxExpensiveConcurrent: number;
    maxDeepConcurrent: number;
    maxCriticalConcurrent: number;
    staleReservationMs: number;
}): GatewayHook;
