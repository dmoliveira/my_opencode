import type { GatewayHook } from "../registry.js";
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
}
export declare function createContinuationHook(options: {
    directory: string;
    client?: GatewayClient;
}): GatewayHook;
export {};
