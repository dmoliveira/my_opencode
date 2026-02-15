import type { GatewayHook } from "../registry.js";
export declare function createDependencyRiskGuardHook(options: {
    directory: string;
    enabled: boolean;
    lockfilePatterns: string[];
    commandPatterns: string[];
}): GatewayHook;
