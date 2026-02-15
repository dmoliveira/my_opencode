import type { GatewayHook } from "../registry.js";
export declare function createSecretLeakGuardHook(options: {
    directory: string;
    enabled: boolean;
    redactionToken: string;
    patterns: string[];
}): GatewayHook;
