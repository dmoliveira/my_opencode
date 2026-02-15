import type { GatewayHook } from "../registry.js";
export interface StopContinuationGuard {
    isStopped(sessionId: string): boolean;
}
export declare function createStopContinuationGuardHook(options: {
    directory: string;
    enabled: boolean;
}): GatewayHook & StopContinuationGuard;
