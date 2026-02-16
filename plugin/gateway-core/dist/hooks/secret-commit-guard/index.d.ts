import type { GatewayHook } from "../registry.js";
export declare function createSecretCommitGuardHook(options: {
    directory: string;
    enabled: boolean;
    patterns: string[];
}): GatewayHook;
