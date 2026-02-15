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
interface ChatMessageInput {
    sessionID?: string;
}
export default function GatewayCorePlugin(ctx: GatewayContext): {
    event(input: GatewayEventPayload): Promise<void>;
    "tool.execute.before"(input: ToolBeforeInput, output: ToolBeforeOutput): Promise<void>;
    "chat.message"(input: ChatMessageInput): Promise<void>;
};
export {};
