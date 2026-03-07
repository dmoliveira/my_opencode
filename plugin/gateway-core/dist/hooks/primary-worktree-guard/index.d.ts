import type { GatewayHook } from "../registry.js";
export declare function createPrimaryWorktreeGuardHook(options: {
    directory: string;
    enabled: boolean;
    allowedBranches: string[];
    blockEdits: boolean;
    blockBranchSwitches: boolean;
}): GatewayHook;
