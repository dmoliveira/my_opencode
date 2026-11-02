import type { GatewayHook } from "../registry.js";
/** Accept only the exact mandatory runtime prefix for this actual session. */
export declare function nativeDependencyCommand(command: string, session: string): {
    command: string;
    prefix: string;
};
/** Conservative native patch grammar; hunk content is never an operation target. */
export declare function patchFileTargets(patch: string): string[] | null;
/** Instrumented command guard, not a sandbox for arbitrary user-authored programs. */
export declare function dependencyCommandRisk(command: string): boolean;
export declare function createDependencyRiskGuardHook(options: {
    directory: string;
    enabled: boolean;
    lockfilePatterns: string[];
    commandPatterns: string[];
}): GatewayHook;
