import type { GatewayHook } from "../registry.js";
interface AssistantMessageInfo {
    role?: string;
    providerID?: string;
    modelID?: string;
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
}
export declare function createProviderTokenLimitRecoveryHook(options: {
    directory: string;
    enabled: boolean;
    client?: GatewayClient;
    cooldownMs: number;
}): GatewayHook;
export {};
