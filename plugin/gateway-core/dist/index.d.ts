interface GatewayEventPayload {
    event: {
        type: string;
        properties?: Record<string, unknown>;
    };
}
interface GatewayContext {
    config?: unknown;
    directory?: string;
    client?: {
        session?: {
            messages(args: {
                path: {
                    id: string;
                };
                query?: {
                    directory?: string;
                };
            }): Promise<{
                data?: Array<{
                    info?: {
                        role?: string;
                    };
                    parts?: Array<{
                        type: string;
                        text?: string;
                    }>;
                }>;
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
            summarize(args: {
                path: {
                    id: string;
                };
                body: {
                    providerID: string;
                    modelID: string;
                    auto: boolean;
                };
                query?: {
                    directory?: string;
                };
            }): Promise<void>;
        };
    };
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
interface ToolAfterInput {
    tool: string;
    sessionID?: string;
}
interface ToolAfterOutput {
    output?: unknown;
    metadata?: unknown;
}
interface ChatMessageInput {
    sessionID?: string;
    prompt?: string;
    text?: string;
    message?: string;
    parts?: Array<{
        type?: string;
        text?: string;
    }>;
}
interface ChatMessageOutput {
    parts?: Array<{
        type: string;
        text?: string;
    }>;
}
export default function GatewayCorePlugin(ctx: GatewayContext): {
    event(input: GatewayEventPayload): Promise<void>;
    "tool.execute.before"(input: ToolBeforeInput, output: ToolBeforeOutput): Promise<void>;
    "tool.execute.after"(input: ToolAfterInput, output: ToolAfterOutput): Promise<void>;
    "chat.message"(input: ChatMessageInput, output?: ChatMessageOutput): Promise<void>;
};
export {};
