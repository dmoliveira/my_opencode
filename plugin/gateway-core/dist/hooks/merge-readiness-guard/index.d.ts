import type { GatewayHook } from "../registry.js";
export declare function createMergeReadinessGuardHook(options: {
    directory: string;
    enabled: boolean;
    requireDeleteBranch: boolean;
    requireStrategy: boolean;
    disallowAdminBypass: boolean;
}): GatewayHook;
