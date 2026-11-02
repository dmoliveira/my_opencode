import type { ToolHooks } from "./types.js";
/** V2 adapter for the existing write and protected-worktree guards only. */
export declare function registerV2WorktreeGuards(tool: ToolHooks, resolveDirectory: (sessionID: string) => Promise<string>, options: {
    directory: string;
    writeExisting: {
        enabled: boolean;
    };
    primary: {
        enabled: boolean;
        allowedBranches: string[];
        blockEdits: boolean;
        blockBranchSwitches: boolean;
    };
    workflow: {
        enabled: boolean;
        protectedBranches: string[];
        blockEditsOnProtectedBranches: boolean;
    };
}): Promise<() => Promise<void>>;
