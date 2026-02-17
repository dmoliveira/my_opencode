import type { GatewayHook } from "../registry.js";
interface GatewayClient {
    session?: {
        messages?(args: {
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
                    agent?: string;
                    model?: {
                        providerID?: string;
                        modelID?: string;
                        variant?: string;
                    };
                    providerID?: string;
                    modelID?: string;
                };
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
    };
}
export declare function createSessionRecoveryHook(options: {
    directory: string;
    client?: GatewayClient;
    enabled: boolean;
    autoResume: boolean;
}): GatewayHook;
export {};
