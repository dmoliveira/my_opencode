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
        tui?: {
            showToast(args?: {
                directory?: string;
                workspace?: string;
                title?: string;
                message?: string;
                variant?: "info" | "success" | "warning" | "error";
                duration?: number;
            }): Promise<unknown>;
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
interface CommandBeforeInput {
    command: string;
    arguments?: string;
    sessionID?: string;
}
interface CommandBeforeOutput {
    parts?: Array<{
        type: string;
        text?: string;
    }>;
}
interface CommandAfterInput {
    command: string;
    arguments?: string;
    sessionID?: string;
}
interface CommandAfterOutput {
    output?: unknown;
}
export declare const GATEWAY_LLM_DECISION_RUNTIME_BINDINGS: {
    readonly agentDeniedToolEnforcer: "agent-denied-tool-enforcer";
    readonly agentModelResolver: "agent-model-resolver";
    readonly delegationFallbackOrchestrator: "delegation-fallback-orchestrator";
    readonly validationEvidenceLedger: "validation-evidence-ledger";
    readonly autoSlashCommand: "auto-slash-command";
    readonly providerErrorClassifier: "provider-error-classifier";
    readonly doneProofEnforcer: "done-proof-enforcer";
    readonly prBodyEvidenceGuard: "pr-body-evidence-guard";
};
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
interface ChatMessagesTransformOutput {
    messages: Array<{
        info?: {
            role?: string;
            id?: string;
            sessionID?: string;
        };
        parts?: Array<{
            type?: string;
            text?: string;
        }>;
    }>;
}
interface ChatSystemTransformOutput {
    system: string[];
}
export default function GatewayCorePlugin(ctx: GatewayContext): {
    event(input: GatewayEventPayload): Promise<void>;
    "tool.execute.before"(input: ToolBeforeInput, output: ToolBeforeOutput): Promise<void>;
    "command.execute.before"(input: CommandBeforeInput, output: CommandBeforeOutput): Promise<void>;
    "command.execute.after"(input: CommandAfterInput, output: CommandAfterOutput): Promise<void>;
    "tool.execute.after"(input: ToolAfterInput, output: ToolAfterOutput): Promise<void>;
    "chat.message"(input: ChatMessageInput, output?: ChatMessageOutput): Promise<void>;
    "experimental.chat.messages.transform"(input: {
        sessionID?: string;
    }, output: ChatMessagesTransformOutput): Promise<void>;
    "experimental.chat.system.transform"(input: {
        sessionID?: string;
        model?: {
            providerID?: string;
            modelID?: string;
        };
    }, output: ChatSystemTransformOutput): Promise<void>;
};
export {};
