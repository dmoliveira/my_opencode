import type { GatewayHook } from "../registry.js";
export declare function createWorkflowConformanceGuardHook(options: {
    directory: string;
    enabled: boolean;
    protectedBranches: string[];
    blockEditsOnProtectedBranches: boolean;
}): GatewayHook;
