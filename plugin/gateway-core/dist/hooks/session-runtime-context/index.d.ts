import type { GatewayHook } from "../registry.js";
interface SessionClient {
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
            };
        }>;
    }>;
}
export declare function createSessionRuntimeContextHook(options: {
    directory: string;
    enabled: boolean;
    client?: {
        session?: SessionClient;
    };
}): GatewayHook;
export {};
