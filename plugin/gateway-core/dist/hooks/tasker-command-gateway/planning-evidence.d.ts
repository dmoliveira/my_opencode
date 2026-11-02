import { type TaskerCommandInspection, type TaskerSandbox } from "./command-policy.js";
type Json = Record<string, unknown>;
export declare function sameTaskerSandbox(a: TaskerSandbox, b: TaskerSandbox): boolean;
export declare function taskerJson(value: unknown): Json | null;
/** Only a worktree-local native doctor can mint one migration capability. */
export declare function safeTaskerDoctor(data: Json, sandbox: TaskerSandbox): boolean;
/** Volatile evidence belongs to one immutable sandbox and mutation generation. */
export declare class TaskerPlanningEvidence {
    private now;
    readonly targets: Map<string, Readonly<{
        scope: string;
        worktree: string;
        branch: string;
    }>>;
    readonly sandbox: TaskerSandbox;
    generation: number;
    busy: string;
    request: string;
    researchCount: number;
    researchPending: Set<string>;
    researchFailed: boolean;
    persisted: boolean;
    private records;
    private revisions;
    private lookup?;
    private linkIDs?;
    private preview?;
    private doctor?;
    constructor(sandbox: TaskerSandbox, initial?: ReadonlyMap<string, TaskerSandbox>, now?: () => number);
    private stamp;
    private fresh;
    invalidate(): void;
    newRequest(key: string): void;
    private record;
    private completeLinks;
    private owns;
    authorize(command: TaskerCommandInspection): string | null;
    reserve(command: TaskerCommandInspection, callID: string): void;
    observe(command: TaskerCommandInspection, output: unknown, exit: unknown): boolean;
    private remember;
}
export {};
