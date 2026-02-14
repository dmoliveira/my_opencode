export type CompletionMode = "promise" | "objective";
export interface AutopilotLoopState {
    active: boolean;
    sessionId: string;
    prompt: string;
    iteration: number;
    maxIterations: number;
    completionMode: CompletionMode;
    completionPromise: string;
    startedAt: string;
}
export interface TextPart {
    type: string;
    text?: string;
}
export interface SessionMessage {
    info?: {
        role?: string;
    };
    parts?: TextPart[];
}
export interface HookEventPayload {
    event: {
        type: string;
        properties?: Record<string, unknown>;
    };
}
export interface HookClient {
    session: {
        messages(args: {
            path: {
                id: string;
            };
            query?: {
                directory?: string;
            };
        }): Promise<{
            data?: SessionMessage[];
        }>;
        promptAsync(args: {
            path: {
                id: string;
            };
            body: {
                parts: Array<{
                    type: string;
                    text: string;
                }>;
            };
            query?: {
                directory?: string;
            };
        }): Promise<void>;
    };
    tui?: {
        showToast(args: {
            body: {
                title: string;
                message: string;
                variant: "success" | "warning" | "info";
                duration: number;
            };
        }): Promise<void>;
    };
}
export interface HookContext {
    directory: string;
    client: HookClient;
}
export interface AutopilotLoopOptions {
    stateFile?: string;
    apiTimeoutMs?: number;
}
