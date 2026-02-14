import type { AutopilotLoopOptions, AutopilotLoopState, HookContext, HookEventPayload } from "./types.js";
export interface AutopilotLoopHook {
    event(input: HookEventPayload): Promise<void>;
    startLoop(args: {
        sessionId: string;
        prompt: string;
        completionMode?: "promise" | "objective";
        completionPromise?: string;
        maxIterations?: number;
    }): void;
    cancelLoop(sessionId: string): void;
    getState(): AutopilotLoopState | null;
}
interface ToolBeforeInput {
    tool: string;
    sessionID?: string;
}
interface ToolBeforeOutput {
    args?: {
        command?: string;
    };
}
interface ChatMessageInput {
    sessionID: string;
}
interface PluginShape {
    event(input: HookEventPayload): Promise<void>;
    "tool.execute.before"(input: ToolBeforeInput, output: ToolBeforeOutput): Promise<void>;
    "chat.message"(input: ChatMessageInput): Promise<void>;
}
export declare function createAutopilotLoopHook(ctx: HookContext, options?: AutopilotLoopOptions): AutopilotLoopHook;
export default function AutopilotLoopPlugin(ctx: HookContext): PluginShape;
export {};
