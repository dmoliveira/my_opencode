import type { GatewayHook } from "../registry.js";
/** Instrumented command guard, not a sandbox for arbitrary user-authored programs. */
export declare function dependencyCommandRisk(command: string): boolean;
export declare function createDependencyRiskGuardHook(options: {
    directory: string;
    enabled: boolean;
    lockfilePatterns: string[];
    commandPatterns: string[];
}): GatewayHook;
