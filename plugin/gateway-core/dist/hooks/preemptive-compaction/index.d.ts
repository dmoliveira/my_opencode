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
}
export declare function createPreemptiveCompactionHook(options: {
    directory: string;
    client?: GatewayClient;
    enabled: boolean;
    warningThreshold: number;
    compactionCooldownToolCalls: number;
    minTokenDeltaForCompaction: number;
    defaultContextLimitTokens: number;
    guardMarkerMode: "nerd" | "plain" | "both";
    guardVerbosity: "minimal" | "normal" | "debug";
    maxSessionStateEntries: number;
}): GatewayHook;
export {};
