interface SessionMessageInfo {
    role?: string;
    agent?: string;
    model?: {
        providerID?: string;
        modelID?: string;
        variant?: string;
    };
    providerID?: string;
    modelID?: string;
    error?: unknown;
    time?: {
        completed?: number;
    };
}
interface SessionMessage {
    info?: SessionMessageInfo;
    parts?: Array<{
        type?: string;
        text?: string;
        synthetic?: boolean;
    }>;
}
interface SessionClient {
    messages?(args: {
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
            agent?: string;
            model?: {
                providerID: string;
                modelID: string;
                variant?: string;
            };
        };
        query?: {
            directory?: string;
        };
    }): Promise<void>;
}
export interface HookMessageIdentity {
    agent?: string;
    model?: {
        providerID: string;
        modelID: string;
        variant?: string;
    };
}
export interface HookMessageSafetyResult {
    safe: boolean;
    reason: "ok" | "history_unavailable" | "history_probe_failed" | "assistant_turn_incomplete";
}
export declare function resolveHookMessageIdentity(args: {
    session: SessionClient;
    sessionId: string;
    directory: string;
}): Promise<HookMessageIdentity>;
export declare function inspectHookMessageSafety(args: {
    session: SessionClient;
    sessionId: string;
    directory: string;
    messages?: SessionMessage[];
}): Promise<HookMessageSafetyResult>;
export declare function buildHookMessageBody(content: string, identity: HookMessageIdentity): {
    parts: Array<{
        type: string;
        text: string;
    }>;
    agent?: string;
    model?: {
        providerID: string;
        modelID: string;
        variant?: string;
    };
};
export declare function injectHookMessage(args: {
    session: SessionClient;
    sessionId: string;
    content: string;
    directory: string;
    maxChars?: number;
}): Promise<boolean>;
export {};
