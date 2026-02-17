import type { GatewayHook } from "../registry.js";
import type { StopContinuationGuard } from "../stop-continuation-guard/index.js";
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
export declare function createTodoContinuationEnforcerHook(options: {
    directory: string;
    enabled: boolean;
    client?: GatewayClient;
    stopGuard?: StopContinuationGuard;
    cooldownMs: number;
    maxConsecutiveFailures: number;
}): GatewayHook;
export {};
