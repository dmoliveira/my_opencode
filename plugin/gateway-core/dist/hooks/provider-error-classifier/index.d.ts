import type { GatewayHook } from "../registry.js";
interface GatewayClient {
    session?: {
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
export declare function createProviderErrorClassifierHook(options: {
    directory: string;
    enabled: boolean;
    client?: GatewayClient;
    cooldownMs: number;
}): GatewayHook;
export {};
