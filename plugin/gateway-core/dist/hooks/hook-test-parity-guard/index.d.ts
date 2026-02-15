import type { GatewayHook } from "../registry.js";
export declare function createHookTestParityGuardHook(options: {
    directory: string;
    enabled: boolean;
    sourcePatterns: string[];
    testPatterns: string[];
    blockOnMismatch: boolean;
}): GatewayHook;
