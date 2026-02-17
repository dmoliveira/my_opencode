import type { GatewayHook } from "../registry.js";
export declare function createNoninteractiveShellGuardHook(options: {
    directory: string;
    enabled: boolean;
    injectEnvPrefix: boolean;
    envPrefixes: string[];
    prefixCommands: string[];
    blockedPatterns: string[];
}): GatewayHook;
