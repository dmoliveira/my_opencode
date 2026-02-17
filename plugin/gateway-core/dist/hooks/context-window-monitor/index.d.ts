import type { GatewayHook } from "../registry.js";
interface AssistantMessageInfo {
    role?: string;
    providerID?: string;
    modelID?: string;
    tokens?: {
        input?: number;
        cache?: {
            read?: number;
        };
    };
}
interface MessageWrapper {
    info?: AssistantMessageInfo;
}
interface GatewayClient {
    session?: {
        messages(args: {
            path: {
                id: string;
            };
            query?: {
                directory?: string;
            };
        }): Promise<{
            data?: MessageWrapper[];
        }>;
    };
}
export declare function createContextWindowMonitorHook(options: {
    directory: string;
    client?: GatewayClient;
    enabled: boolean;
    warningThreshold: number;
    reminderCooldownToolCalls: number;
    minTokenDeltaForReminder: number;
    defaultContextLimitTokens: number;
    guardMarkerMode: "nerd" | "plain" | "both";
    guardVerbosity: "minimal" | "normal" | "debug";
    maxSessionStateEntries: number;
}): GatewayHook;
export {};
