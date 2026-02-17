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
}
interface SessionMessage {
    info?: SessionMessageInfo;
}
interface SessionClient {
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
export declare function injectHookMessage(args: {
    session: SessionClient;
    sessionId: string;
    content: string;
    directory: string;
}): Promise<boolean>;
export {};
