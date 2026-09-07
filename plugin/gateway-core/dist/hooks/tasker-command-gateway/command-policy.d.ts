export type TaskerSandbox = Readonly<{
    scope: string;
    worktree: string;
    branch: string;
}>;
export type TaskerCommandContext = Readonly<{
    sandbox?: TaskerSandbox;
    knownRecordIds?: ReadonlySet<string>;
    knownRecordTargets?: ReadonlyMap<string, TaskerSandbox>;
}>;
export type TaskerCommandInspection = Readonly<{
    kind: "read" | "write";
    verb: string;
    positionals: readonly string[];
    options: Readonly<Record<string, readonly string[]>>;
}>;
export declare function inspectTaskerCommand(command: string, context?: TaskerCommandContext): readonly TaskerCommandInspection[] | null;
export declare function isAllowedTaskerCommand(command: string, context?: TaskerCommandContext): boolean;
export declare function extractTaskerRecordIds(value: unknown): Set<string>;
