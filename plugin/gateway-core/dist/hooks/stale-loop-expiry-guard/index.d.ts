import type { GatewayHook } from "../registry.js";
export declare function createStaleLoopExpiryGuardHook(options: {
    directory: string;
    enabled: boolean;
    maxAgeMinutes: number;
}): GatewayHook;
