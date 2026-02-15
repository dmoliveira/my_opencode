import type { GatewayHook } from "../registry.js";
export declare function createNoninteractiveShellGuardHook(options: {
    directory: string;
    enabled: boolean;
    blockedPatterns: string[];
}): GatewayHook;
