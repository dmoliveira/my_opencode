import type { GatewayHook } from "../registry.js";
export declare function createDangerousCommandGuardHook(options: {
    directory: string;
    enabled: boolean;
    blockedPatterns: string[];
}): GatewayHook;
