import type { GatewayHook } from "../registry.js";
export interface StopContinuationGuard {
    isStopped(sessionId: string): boolean;
    forceStop(sessionId: string, reasonCode?: string): void;
}
export declare function createStopContinuationGuardHook(options: {
    directory: string;
    enabled: boolean;
}): GatewayHook & StopContinuationGuard;
