export type TaskerReadAuthority = {
    worktree: string;
    paths: readonly string[];
};
/** Authorizes the actual native tool target, not just instructions in its prompt. */
export declare function authorizeTaskerRead(tool: string, args: Record<string, unknown>, authority: TaskerReadAuthority): boolean;
