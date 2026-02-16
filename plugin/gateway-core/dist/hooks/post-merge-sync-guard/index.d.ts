import type { GatewayHook } from "../registry.js";
export declare function createPostMergeSyncGuardHook(options: {
    directory: string;
    enabled: boolean;
    requireDeleteBranch: boolean;
    enforceMainSyncInline: boolean;
    reminderCommands: string[];
}): GatewayHook;
