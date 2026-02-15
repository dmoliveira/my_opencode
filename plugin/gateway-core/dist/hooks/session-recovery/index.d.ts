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
export declare function createSessionRecoveryHook(options: {
    directory: string;
    client?: GatewayClient;
    enabled: boolean;
    autoResume: boolean;
}): GatewayHook;
export {};
