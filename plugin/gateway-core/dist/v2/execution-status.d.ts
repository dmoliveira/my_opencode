import type { Registration } from "./types.js";
type ToolEvent = {
    tool: string;
    sessionID: string;
    input: unknown;
    status?: string;
    result?: unknown;
};
interface StatusToolHooks {
    hook(name: "execute.before" | "execute.after", callback: (event: ToolEvent) => Promise<void>): Promise<Registration>;
}
interface StatusContext {
    app: {
        version: string;
    };
    location: {
        directory: string;
    };
    session: {
        get(input: {
            sessionID: string;
        }): Promise<{
            location?: {
                directory?: unknown;
            };
        }>;
    };
    tool: StatusToolHooks;
    event: {
        subscribe(options: {
            types: string[];
            signal: AbortSignal;
        }): AsyncIterable<unknown>;
    };
}
/** Unconfigured V2 adapter; status reporting is never an enforcement boundary. */
export declare function registerV2ExecutionStatus(context: StatusContext, options: {
    enabled: boolean;
    maxSessions: number;
    maxLabelChars: number;
}): Promise<() => Promise<void>>;
export {};
